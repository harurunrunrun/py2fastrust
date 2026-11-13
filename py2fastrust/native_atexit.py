"""Canonical termination callbacks compiled from captured typed call sites."""
import ast
from dataclasses import dataclass

from .native_classes import FunctionPlan


class ShutdownPlan(FunctionPlan):
    _native_atexit_callback=True
    @property
    def scope(self):return '<atexit>'


@dataclass
class Registration:
    index:int
    parent:object
    node:object
    callback:object
    positional:tuple
    keywords:tuple
    metadata:object
    plan:object
    site:object=None
    emitted:bool=False
    helper:str|None=None


@dataclass
class MemberCall:
    result:object
    error:str|None=None
    registration:object=None


def registry(model):
    value=getattr(model,'atexit_callbacks',None)
    if value is None:value=model.atexit_callbacks=Registry(model)
    return value


class Registry:
    def __init__(self,model):
        self.model=model;self.records=[];self.sites={};self.used=False

    def registration(self,parent,node,metadata,positional,keywords,environment):
        from .native_classes import Cell,ClassUnsupported,shape
        from .native_aot_callables import function_kind
        from .native_class_stdio import CALLABLES
        from .native_types import alternatives,EMPTY
        callback=positional[0]
        choices=alternatives(shape(callback))
        noncallable={'int','bool','int_bool','float','none','str','bytes','range'}
        if any(kind in noncallable for kind in choices)and any(function_kind(kind)or kind in CALLABLES for kind in choices):
            raise ClassUnsupported(node,'atexit.register() has both callable and noncallable alternatives; preserving conditional registration and its callable check needs a finite registration binding adapter',types=(('callback',shape(callback)),),proof='finite atexit callable binding')
        for kind in choices:
            if kind is None:continue
            if function_kind(kind)or kind in CALLABLES:continue
            if kind in {'int','bool','int_bool','float','none','str','bytes','range'}:
                return MemberCall(Cell(EMPTY),'TypeError: the first argument must be callable')
            raise ClassUnsupported(node,'atexit.register() needs a canonical native function, builtin, stream callable or bound source method; custom callable objects and constructor callbacks require additional deferred-call protocols',types=(('callback',kind),),proof='typed atexit callable protocol')
        key=parent.index,id(node)
        record=self.sites.get(key)
        if record is None:
            if self.model.unit is None:
                raise ClassUnsupported(node,'atexit callbacks require the official source unit and lexical scopes; that lifecycle ownership metadata is unavailable',proof='official atexit callback source ownership')
            origin=self.model.unit.original_unit(node)if hasattr(self.model.unit,'original_unit')else self.model.unit
            deferred=ShutdownPlan(origin.tree,len(self.model.plans),reachable=True,
                source_unit=parent.source_unit,module_name=parent.module_name)
            deferred.result=Cell('none')
            self.model.plans.append(deferred)
            record=Registration(len(self.records),parent,node,callback,tuple(positional[1:]),tuple(keywords),metadata,deferred)
            deferred.atexit_registration=record
            self.records.append(record);self.sites[key]=record
        else:
            record.callback=callback;record.positional=tuple(positional[1:]);record.keywords=tuple(keywords);record.metadata=metadata
        self.used=True
        self.model.exceptions.require(node)
        return MemberCall(callback,registration=record)

    def analyze_body(self,plan,environment):
        from .native_classes import Environment,ClassUnsupported,shape
        from .native_guard_flow import AnalysisPending
        from .native_aot_callables import analyze_values
        from .call_semantics import Argument,CallArguments
        record=plan.atexit_registration
        if shape(record.callback)is None:
            if not self.model.final:raise AnalysisPending()
            raise ClassUnsupported(record.node,'the atexit callback target remains unresolved at shutdown',proof='finite deferred atexit callable identity')
        # These are possible future module names, not a claim that they will
        # actually have been initialized. Runtime namespace presence remains
        # separate from source-level type/schema inference.
        names=set(self.model.global_symbols)
        names.update(binding.name for binding in self.model.iter_bindings()if self.model.module_owner(binding.owner))
        plan.global_names=names
        plan.visible_definitions=set(self.model.functions)
        future=Environment(self.model.global_symbols,definite=())
        metadata=CallArguments(tuple(Argument(item.expression)for item in record.metadata.positional[1:]),
                              tuple(record.metadata.keywords))
        record.site=analyze_values(self.model.callable_cells,plan,record.node,record.callback,
            metadata,list(record.positional),list(record.keywords),future,
            identity=('atexit_shutdown',record.index))
        self.observe_callback(record)
        return None

    def observe_callback(self,record):
        from .native_aot_callables import function_kind
        from .native_bound_methods import BoundMethodTarget
        from .native_class_descriptors import ClassMethodTarget
        from .native_classes import shape,ClassUnsupported,InstanceType
        from .native_class_identity_demand import observe_implicit
        from .native_source_lengths import member
        from .native_types import alternatives
        receivers=[]
        for kind in alternatives(shape(record.callback)):
            if not function_kind(kind):
                raise ClassUnsupported(record.node,'atexit callback error reporting needs this stream/callable object representation; the initial callback observer supports canonical function references and ordinary bound source methods',proof='atexit unraisable callable representation')
            for target in kind.methods:
                if isinstance(target,ClassMethodTarget)and not getattr(target,'_native_instance_function_target',False):
                    raise ClassUnsupported(record.node,'atexit error reporting for bound classmethods needs their class-object representation; that observer is not implemented',proof='atexit classmethod representation')
                receiver=getattr(target,'_native_receiver_kind',InstanceType(target.owner))
                if not isinstance(receiver,InstanceType):
                    raise ClassUnsupported(record.node,'atexit bound callable reporting needs this noninstance receiver representation',proof='atexit bound receiver representation')
                if member(self.model,receiver,('__repr__',),record.node)is not None:
                    raise ClassUnsupported(record.node,'atexit bound callback reporting can invoke a custom receiver __repr__; that unraisable observer callback protocol is not implemented',proof='atexit custom receiver repr')
                receivers.append(receiver)
        observe_implicit(self.model,record.parent,record.node,('atexit_callback_repr',record.index),
                         receivers,'atexit unraisable callback representation observes receiver identity')

    def generate(self,emitter):
        from .native_classes import Expression,shape,ClassUnsupported
        from .native_aot_callables import emit_values
        record=emitter.plan.atexit_registration
        if emitter.plan.index not in self.model.synchronous_calls:
            raise ClassUnsupported(record.node,'atexit callback invocation needs a recursive/asynchronous continuation; this shutdown slice implements synchronous typed callback bodies',proof='synchronous atexit callback call')
        kinds=[shape(record.callback),*(shape(cell)for cell in record.positional),*(shape(cell)for _,cell in record.keywords)]
        if any(kind is None for kind in kinds):
            raise ClassUnsupported(record.node,'an atexit retained argument or callback remains unresolved after inference',proof='complete typed atexit payload')
        self.observe_callback(record)
        self.validate_payload(record)
        emitter.logical_scope='<atexit>'
        emitter.primitive_parameters={};emitter.readonly_owned_parameters={}
        emitter.owned_local_lists={};emitter.owned_matrices={};emitter.record_places={}
        positional=[Expression('argument_'+str(index),shape(cell))for index,cell in enumerate(record.positional)]
        keywords=[(name,Expression('keyword_'+str(index),shape(cell)))for index,(name,cell)in enumerate(record.keywords)]
        callee=Expression('callback',shape(record.callback))
        result=emit_values(emitter,record.node,record.site,callee,positional,keywords,shape(record.site.result))
        parameters=['class_scope:ClassScope','callback:'+emitter.rust_type(callee.kind)]
        parameters.extend(value.code+':'+emitter.rust_type(value.kind)for value in positional)
        parameters.extend(value.code+':'+emitter.rust_type(value.kind)for _,value in keywords)
        record.helper='fn class_atexit_invoke_'+str(record.index)+'('+','.join(parameters)+')->ClassResult<()>{let _='+result.code+';Ok(())}'
        return record.helper

    def validate_payload(self,record):
        """Prove real retained layouts, without treating unknown edges as leaves.

        The registry is inaccessible from Python and therefore cannot itself
        be reached from a retained value. Its payloads retain the ordinary
        existing Rc handles; no proxy or new ownership relation is introduced.
        Source modules already have process lifetime. Local lexical data and
        receiver fields need their own complete, acyclic owned layout proof.
        """
        from .native_classes import ClassUnsupported,InstanceType,shape
        from .native_aot_callables import function_kind
        from .native_types import (ListType,TupleType,TupleSequenceType,NullableType,
                                   MaybeType,UnionType,EmptyType)
        visiting=set();done=set()
        def fail(message,kind=None):
            raise ClassUnsupported(record.node,message,
                types=()if kind is None else(('retained atexit value',kind),),
                proof='complete owned atexit callback payload')
        def enter(key,body):
            if key in visiting:fail('atexit retention reaches a captured reference cycle; cycle-aware shutdown payload tracing is not implemented')
            if key in done:return
            visiting.add(key);body();visiting.remove(key);done.add(key)
        def environment(scope):
            owned=self.model.lexical.environments.get(scope)
            if owned is None:fail('a retained atexit callback has no actual owned lexical environment layout')
            def contents():
                if owned.parent is not None and not self.model.module_owner(owned.parent):environment(owned.parent)
                for cell in (*owned.fields.values(),*owned.defaults.values()):value(shape(cell))
            enter(('environment',scope),contents)
        def definition(ordinal):
            source=self.model.callable_cells.plans.get(ordinal)
            if source is None:fail('a retained atexit function has no canonical source definition')
            def contents():
                parent=self.model.lexical.parent_scope(source)
                if parent is not None:environment(parent)
                for cell in source.default_cells.values():value(shape(cell))
            enter(('function',ordinal),contents)
        def value(kind):
            if isinstance(kind,EmptyType)or kind in {'int','bool','int_bool','none','float','complex','str','bytes','range'}:return
            if isinstance(kind,(ListType,TupleSequenceType)):value(kind.element);return
            if isinstance(kind,TupleType):
                for child in kind.fields:value(child)
                return
            if isinstance(kind,(NullableType,MaybeType)):value(kind.value);return
            if isinstance(kind,UnionType):
                for child in kind.alternatives:value(child)
                return
            if function_kind(kind):
                for ordinal in kind.definitions:definition(ordinal)
                for target in kind.methods:definition(target.definition)
                for owned in kind._native_owned_kinds:value(owned)
                return
            if isinstance(kind,InstanceType):
                if kind.name in getattr(self.model,'gc_classes',()):
                    fail('atexit retains a collected source instance; shutdown registry roots for cyclic class payloads are not implemented',kind)
                owner=self.model.classes.get(kind.name)
                if owner is None:fail('atexit retains a source instance with no actual owned field layout',kind)
                enter(('object',kind.name),lambda:[value(shape(field.cell))for field in owner.fields.values()])
                return
            fail('atexit retains an unresolved value or provider whose complete shutdown ownership facet is not implemented',kind)
        value(shape(record.callback))
        for cell in (*record.positional,*(cell for _,cell in record.keywords)):value(shape(cell))

    def push(self,emitter,node,record,positional,keywords):
        from .native_classes import Expression,shape
        from .native import _string
        if record.error:
            return Expression(emitter.at('Err::<'+emitter.rust_type(shape(record.result))+',String>('+_string(record.error)+'.to_owned())',node),shape(record.result))
        if record.registration is None:
            if record.result.root().tag=='int':
                return Expression('class_from_usize(CLASS_ATEXIT_CALLBACKS.with(|entries|entries.borrow().len()))','int')
            return Expression('{CLASS_ATEXIT_CALLBACKS.with(|entries|entries.borrow_mut().clear());()}','none')
        registration=record.registration;registration.emitted=True
        callback=positional[0]
        retained=emitter.fresh()
        fields=['callback:('+callback.code+').clone()']
        fields.extend('argument_'+str(index)+':('+value.code+').clone()'for index,value in enumerate(positional[1:]))
        fields.extend('keyword_'+str(index)+':('+value.code+').clone()'for index,(name,value)in enumerate(keywords))
        push='CLASS_ATEXIT_CALLBACKS.with(|entries|{let mut entries=entries.borrow_mut();entries.try_reserve(1).map_err(|_|"MemoryError: cannot retain atexit callback".to_owned())?;entries.push(ClassAtexitEntry::R'+str(registration.index)+'{'+','.join(fields)+'});Ok::<(),String>(())})'
        return Expression('{let '+retained+'=('+callback.code+').clone();'+emitter.at(push,node)+';'+retained+'}',shape(record.result))

    def declarations(self,emitter):
        from .native_classes import Expression,shape,ClassUnsupported,InstanceType
        from .native_aot_callables import AotFunctionType
        from .native_bound_methods import BoundMethodTarget
        from .native_callable_carriers import dispatch,comparison
        from .native_callable_display import emit as builtin_display
        from .native import _string
        entries=[record for record in self.records if record.emitted]
        variants=[];calls=[];needs=[];descriptions=[]
        for record in entries:
            fields=[('callback',shape(record.callback))]
            fields.extend(('argument_'+str(index),shape(cell))for index,cell in enumerate(record.positional))
            fields.extend(('keyword_'+str(index),shape(cell))for index,(_,cell)in enumerate(record.keywords))
            variants.append('R'+str(record.index)+'{'+','.join(name+':'+emitter.rust_type(kind)for name,kind in fields)+'}')
            pattern='Self::R'+str(record.index)+'{'+','.join(name for name,kind in fields)+'}'
            calls.append(pattern+'=>class_atexit_invoke_'+str(record.index)+'(scope.clone(),'+','.join('('+name+').clone()'for name,kind in fields)+')')
            kind=shape(record.callback)
            needs.append('Self::R'+str(record.index)+'{callback,..}=>'+dispatch(emitter,kind,'callback',lambda target,payload:'true'if isinstance(target,int)else'false',borrow=True))
            def describe(target,payload):
                if isinstance(target,int):
                    source=self.model.callable_cells.plans[target]
                    name=getattr(source,'qualified_name',getattr(source.node,'name','<lambda>'))
                    return 'format!("<function {} at 0x{:x}>",'+_string(name)+',address)'
                if isinstance(target,BoundMethodTarget):
                    source=self.model.callable_cells.plans[target.definition]
                    name=getattr(source,'qualified_name',source.node.name)
                    receiver=Expression(payload+'.bound.receiver',InstanceType(target.owner))
                    shown=emitter.show(receiver,record.node,True)
                    return 'format!("<bound method {} of {}>",'+_string(name)+','+shown+')'
                singleton=AotFunctionType.from_targets((target,))
                return builtin_display(emitter,Expression(payload,singleton),record.node)
            descriptions.append('Self::R'+str(record.index)+'{callback,..}=>'+dispatch(emitter,kind,'callback',describe,borrow=True))
        equal=[]
        for first in entries:
            for second in entries:
                expression=comparison(emitter,Expression('left',shape(first.callback)),Expression('right',shape(second.callback)),identity=True)
                equal.append('(Self::R'+str(first.index)+'{callback:left,..},Self::R'+str(second.index)+'{callback:right,..})=>'+expression)
        def match(arms):return 'match self{'+','.join(arms)+'}'if arms else'match *self{}'
        enum='#[derive(Clone)]enum ClassAtexitEntry{'+','.join(variants)+'}'
        methods=('impl ClassAtexitEntry{fn invoke(&self,scope:&ClassScope)->ClassResult<()>{'+match(calls)+'}'
                 'fn needs_identity(&self)->bool{'+match(needs)+'}'
                 'fn describe(&self,address:usize)->String{'+match(descriptions)+'}'
                 'fn same_callback(&self,other:&Self)->bool{'+('match(self,other){'+','.join(equal)+'}'if equal else'match *self{}')+'}}')
        return enum+methods+RUNTIME


class AtexitAdapter:
    NAMES=frozenset({'register','_clear','_ncallbacks'})

    @staticmethod
    def analyze(model,plan,node,identity,metadata,positional,keywords,environment,*,factory):
        from .native_types import EMPTY
        state=registry(model);state.used=True
        model.exceptions.require(node)
        if identity.name=='register':
            if not positional:return MemberCall(factory(EMPTY),'TypeError: register() takes at least 1 argument (0 given)')
            return state.registration(plan,node,metadata,positional,keywords,environment)
        error=('TypeError: atexit.'+identity.name+'() takes no keyword arguments'if keywords else
               'TypeError: atexit.'+identity.name+'() takes no arguments ('+str(len(positional))+' given)'if positional else None)
        return MemberCall(factory(EMPTY if error else'int'if identity.name=='_ncallbacks'else'none'),error)

    @staticmethod
    def emit(emitter,node,identity,record,positional,keywords):
        return registry(emitter.model).push(emitter,node,record,positional,keywords)


RUNTIME=r'''
thread_local!{static CLASS_ATEXIT_CALLBACKS:RefCell<Vec<ClassAtexitEntry>>=const{RefCell::new(Vec::new())};}
fn class_atexit_sanitize(error:&mut NativeError){
 error.frames.retain(|(_,location)|location.1!="<atexit>");
 if error.function.1=="<atexit>"{error.origin_visible=false;}
 if let Some(cause)=error.cause.as_mut(){class_atexit_sanitize(cause);}
 if let Some(context)=error.context.as_mut(){class_atexit_sanitize(context);}
 class_exception_sync(error);
}
fn class_atexit_run(scope:&ClassScope){
 struct Snapshot{entry:ClassAtexitEntry,identity:Option<Rc<u8>>}
 let entries=CLASS_ATEXIT_CALLBACKS.with(|entries|{
  let entries=entries.borrow();let mut snapshot=Vec::new();
  snapshot.try_reserve_exact(entries.len()).map_err(|_|"MemoryError: cannot copy atexit callbacks")?;
  snapshot.extend(entries.iter().cloned().map(|entry|Snapshot{entry,identity:None}));Ok::<_,&str>(snapshot)
 });
 let mut entries=match entries{Ok(entries)=>entries,Err(message)=>{eprintln!("Exception ignored while copying atexit callbacks:\n{}",message);return;}};
 scope.control.borrow_mut().depth=0;
 for index in (0..entries.len()).rev(){
  if let Err(mut error)=entries[index].entry.invoke(scope){
   let mut address=0_usize;
   if entries[index].entry.needs_identity(){
    let identity=entries.iter().find_map(|previous|if entries[index].entry.same_callback(&previous.entry){previous.identity.clone()}else{None}).unwrap_or_else(||Rc::new(0_u8));
    address=Rc::as_ptr(&identity)as usize;entries[index].identity=Some(identity);
   }
   eprintln!("Exception ignored in atexit callback {}:",entries[index].entry.describe(address));
   class_atexit_sanitize(&mut error);class_exception_render_error(&error);
  }
 }
 drop(entries);
 CLASS_ATEXIT_CALLBACKS.with(|entries|entries.borrow_mut().clear());
}
'''


def runtime(source,model):
    state=getattr(model,'atexit_callbacks',None)
    if state is None or not state.used:return source
    from .native_classes import ClassUnsupported
    emitter=model.emitter(model.module)
    support=state.declarations(emitter)
    from .rust_pruning import _lex
    tokens,_,pairs=_lex(source)
    starts=[i for i,token in enumerate(tokens[:-2])if token.text=='fn'and tokens[i+1].text=='main']
    if len(starts)!=1:raise ClassUnsupported(model.tree,'atexit shutdown has no unique native process entry boundary',proof='native atexit process finalization entry')
    opening=next(i for i in range(starts[0],len(tokens))if tokens[i].text=='{');closing=pairs[opening]
    marker='std::io::stdout().write_all(scope.io.borrow().output.as_bytes()).unwrap();'
    boundary=source.find(marker,tokens[opening].end,tokens[closing].start)
    if boundary<0:raise ClassUnsupported(model.tree,'atexit shutdown cannot prove the native buffered-output finalization boundary',proof='native atexit output/status finalization')
    status=('if let Some(exit)=&error.native_exit{if exit.print_payload{eprintln!("{}",(exit.render)());}exit.status}else{class_exception_render_error(error);1}'
            if getattr(model,'native_exit_used',False)else'class_exception_render_error(error);1')
    tail='let class_exit_status=match &result{Ok(_)=>0,Err(error)=>{'+status+'}};'
    flush='{let output=std::mem::take(&mut scope.io.borrow_mut().output);std::io::stdout().write_all(output.as_bytes()).unwrap();}'
    tail=flush+tail+'class_atexit_run(&scope);'+flush+'if class_exit_status!=0{std::process::exit(class_exit_status);}'
    return source[:boundary]+tail+source[tokens[closing].start:]+support
