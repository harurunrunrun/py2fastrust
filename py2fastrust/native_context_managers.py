"""Typed source context managers and native control-flow cleanup regions."""
import ast
from dataclasses import dataclass

from .call_semantics import Argument,CallArguments,CallBindingError


@dataclass(frozen=True)
class ErasedContextArgument:
    _native_kind_tag='erased_context_argument'
    _native_erased_argument=True
    _native_reference_cloneable=True
    _native_stored_reference=True


ERASED=ErasedContextArgument()


@dataclass
class ContextItem:
    original:object
    manager:object
    owner:object
    enter_member:object
    exit_member:object
    enter_site:object=None
    exit_site:object=None


class ContextManagers:
    def __init__(self,model):
        self.model=model
        self.sites={}
        from .native_callback_effects import register
        register(model,self.may_call)

    def may_call(self,plan,node):
        return bool(self.sites.get((plan.index,id(node))))

    @property
    def used(self):return bool(self.sites)

    def _erase_exception_parameters(self,method,node):
        from .native_classes import Cell,ClassUnsupported
        arguments=CallArguments(tuple(Argument(node.context_expr)for _ in range(3)),())
        try:binding=method.signature.plan(arguments,implicit_count=1,allow_variadic=True)
        except CallBindingError:return
        erased=set()
        for name,source in zip(binding.parameters,binding.sources):
            if source.kind=='argument'or source.kind=='variadic'and any(part.kind=='argument'for part in source.items):erased.add(name)
        scope=self.model.unit.scope_for(method.node).ordinal
        original_nodes={}
        for value in ast.walk(method.node):
            try:original_nodes[self.model.unit.ordinal(value)]=value
            except KeyError:pass
        # Raw official bindings include child closure/default and lazy
        # annotation captures, beyond the currently executable-node walk.
        for binding in self.model.unit.bindings:
            if binding.owner==scope and binding.name in erased and binding.role=='load':
                original=original_nodes.get(binding.node,method.node)
                raise ClassUnsupported(original,"this __exit__ implementation observes an exception argument, including captures in nested scopes or default expressions; native exception type, value and traceback objects are not implemented yet",operation="context manager exception argument "+repr(self.model.display_name(binding.name)),proof="unobservable erased context exception arguments")
        # Current typed frames reject frame introspection globally. Keep an
        # explicit erasure boundary so later introspection support cannot make
        # these compiler-only arguments visible as invented Python objects.
        for value in ast.walk(method.node):
            if isinstance(value,ast.Name)and isinstance(value.ctx,ast.Load):
                identity=self.model.builtin_identity(method,value,{})
                from .references import BuiltinIdentity
                if isinstance(identity,BuiltinIdentity)and identity.name in {'locals','eval','exec','vars'}:
                    raise ClassUnsupported(value,"frame introspection can observe erased __exit__ exception arguments; native exception objects and frame-local metadata must be implemented before this context manager can be lowered",proof="context exception argument erasure excludes frame introspection")
            if isinstance(value,ast.Attribute)and value.attr in {'_getframe','currentframe','f_locals','f_back'}:
                raise ClassUnsupported(value,"this frame metadata lookup may expose __exit__ exception arguments; native frame and exception metadata objects are not implemented",proof="context exception argument erasure excludes frame metadata")
        known=getattr(method,'erased_context_parameters',set())
        for name in erased-known:method.arguments[name]=Cell(ERASED)
        method.erased_context_parameters=known|erased

    def _item(self,plan,item,environment):
        from .native_classes import ClassUnsupported,InstanceType,shape
        manager=self.model.expression(plan,item.context_expr,environment)
        kind=shape(manager)
        if kind is None and not self.model.final:return None
        if not isinstance(kind,InstanceType):
            raise ClassUnsupported(item.context_expr,"this with manager needs a proved source-instance special-method lookup; finite manager alternatives and builtin/custom context-manager protocols are not implemented",types=(("manager",kind),),proof="native source context-manager special-method lookup")
        registry=getattr(self.model,'class_namespaces',None)
        if registry is None:raise ClassUnsupported(item.context_expr,"source context managers require the retained class namespace and method-function carriers",proof="context-manager retained class identity")
        owner=self.model.classes[kind.name]
        members=[]
        for name in ('__enter__','__exit__'):
            method=owner.methods.get(name)
            if method is None:
                raise ClassUnsupported(item.context_expr,"source class "+repr(owner.node.name)+" has no registered "+name+" method; this manager's Python protocol error adapter is not implemented",proof="complete context-manager special methods")
            member=registry.member(owner,name)
            if member.descriptor!='function':
                raise ClassUnsupported(item.context_expr,"this context-manager special method is a nonfunction descriptor; descriptor-aware implicit special-method calls are not implemented",proof="context-manager special-method descriptor binding")
            registry.observe_method(member,item.context_expr)
            members.append(member)
        self._erase_exception_parameters(members[1].plan,item)
        return ContextItem(item,manager,owner,*members)

    def analyze(self,plan,node,environment):
        from .native_classes import Cell,Environment,shape
        from .native_aot_callables import analyze_values
        records=[]
        self.sites[(plan.index,id(node))]=records
        def descend(index,current):
            item=node.items[index]
            record=self._item(plan,item,current)
            if record is None:
                from .native_guard_flow import AnalysisPending
                raise AnalysisPending()
            records.append(record)
            enter_arguments=CallArguments((Argument(item.context_expr),),())
            record.enter_site=analyze_values(self.model.callable_cells,plan,node,record.enter_member.function_cell,enter_arguments,[record.manager],[],current,identity=('context_enter',index))
            entry=Environment(current)
            if item.optional_vars is not None:self.model.target(plan,item.optional_vars,record.enter_site.result,current)
            normal=(descend(index+1,current)if index+1<len(node.items)else self.model.block(plan,node.body,current))
            exit_arguments=CallArguments(tuple(Argument(item.context_expr)for _ in range(4)),())
            effect=Environment(normal if normal is not None else entry)
            record.exit_site=analyze_values(self.model.callable_cells,plan,node,record.exit_member.function_cell,exit_arguments,[record.manager]+[Cell(ERASED)for _ in range(3)],[],effect,identity=('context_exit',index))
            exit_kind=shape(record.exit_site.result)
            if exit_kind is None:
                from .native_guard_flow import AnalysisPending
                if not self.model.final:raise AnalysisPending()
                from .native_classes import ClassUnsupported
                raise ClassUnsupported(item.context_expr,'the context manager __exit__ result is unresolved, so its exception-suppression behavior has no native control-flow representation',proof='resolved context-manager exit result')
            if exit_kind=='none':return effect if normal is not None else None
            continuation=self.model.join(normal,entry,node,'with_exception_suppression')
            # The cleanup call can mutate shared/module bindings on either path.
            self.model.namespace.call_effects(plan,record.exit_member.plan,continuation)
            return continuation
        return descend(0,environment)

    def emit(self,emitter,node):
        from .native_classes import Expression,shape
        from .native_module_linking import ClassReferenceType
        from .native_aot_callables import emit_values
        from .native_class_calls import synchronous
        records=self.sites[(emitter.plan.index,id(node))]
        result_kind=shape(emitter.plan.result)
        result_type=emitter.rust_type(result_kind)
        def emit_item(index):
            record=records[index];item=record.original
            setup,manager=emitter.capture(emitter.expression(item.context_expr))
            reference=emitter.fresh()
            setup+=f'let {reference}={{{manager.code}.borrow().class_definition.clone()}};'
            class_reference=Expression(reference,ClassReferenceType(record.owner.index))
            # __exit__ lookup is retained before calling __enter__, as in Python.
            before,exit_function=emitter.capture(self.model.class_namespaces.emit_get(emitter,node,class_reference,record.exit_member));setup+=before
            before,enter_function=emitter.capture(self.model.class_namespaces.emit_get(emitter,node,class_reference,record.enter_member));setup+=before
            retained_manager=Expression(manager.code+".clone()",manager.kind)
            state=getattr(self.model,'source_state',None)
            producer=None if state is None else state.bridges.get((emitter.plan.index,id(node)))
            witness=emitter.fresh()if producer is not None else None
            previous_request=getattr(emitter,'source_state_enter_request',None)
            if producer is not None:
                setup+='let '+witness+':'+emitter.rust_type(producer.slot.kind)+';'
                emitter.source_state_enter_request=producer,witness
            try:
                entered=emit_values(emitter,node,record.enter_site,enter_function,[retained_manager],[],shape(record.enter_site.result),source_call_location=item.context_expr)
            finally:
                emitter.source_state_enter_request=previous_request
            before,value=emitter.capture(entered);setup+=before
            boundaries=getattr(emitter,'context_flow_boundaries',None)
            if boundaries is None:boundaries=emitter.context_flow_boundaries=[]
            depth=len(emitter.loops)
            boundaries.append(depth)
            previous_state=getattr(emitter,'source_state_active',None)
            if producer is not None:
                emitter.source_state_active=(state.modes['with',emitter.plan.index,id(node)],{producer.slot.key:witness})
            try:
                body=emitter.assign(item.optional_vars,value)if item.optional_vars is not None else ''
                body+=emit_item(index+1)if index+1<len(records)else emitter.statements(node.body)
            finally:
                emitter.source_state_active=previous_state
            boundaries.pop()
            outcome=emitter.fresh();cleanup=emitter.fresh();exit_value=emitter.fresh()
            body+='Ok(ClassWithFlow::Normal)'
            if synchronous(self.model,emitter.plan):
                region=f'(||->ClassResult<ClassWithFlow<{result_type}>>{{{body}}})()'
            else:region=f'(async{{{body}}}).await'
            setup+=f'let {outcome}:ClassResult<ClassWithFlow<{result_type}>>={region};'
            exited=emit_values(emitter,node,record.exit_site,exit_function,[retained_manager]+[Expression('()',ERASED)for _ in range(3)],[],shape(record.exit_site.result),source_call_location=item.context_expr)
            cleanup_body='Ok('+exited.code+')'
            if synchronous(self.model,emitter.plan):
                region=f'(||->ClassResult<{emitter.rust_type(exited.kind)}>{{{cleanup_body}}})()'
            else:region=f'(async{{{cleanup_body}}}).await'
            setup+=f'let {cleanup}:ClassResult<{emitter.rust_type(exited.kind)}>={region};'
            error=emitter.fresh();previous=emitter.fresh()
            setup+=f'let {exit_value}=match {cleanup}{{Ok(value)=>value,Err(mut {error})=>{{if let Err({previous})={outcome}{{class_with_attach_context(&mut {error},{previous});}}return Err({error});}}}};'
            dispatch=[]
            dispatch.append('Ok(ClassWithFlow::Normal)=>()')
            dispatch.append('Ok(ClassWithFlow::Return(value))=>'+_return_value(emitter,'value'))
            dispatch.append('Ok(ClassWithFlow::Break)=>'+_loop_transfer(emitter,False))
            dispatch.append('Ok(ClassWithFlow::Continue)=>'+_loop_transfer(emitter,True))
            from .native_builtin_singletons import has_singleton
            truth=emitter.truth(Expression(exit_value,exited.kind),item.context_expr)
            if has_singleton(exited.kind):
                checked=emitter.fresh()
                dispatch.append(f'Err(previous)=>{{let {checked}:ClassResult<bool>=(||->ClassResult<bool>{{Ok({truth})}})();match {checked}{{Ok(true)=>(),Ok(false)=>return Err(previous),Err(mut error)=>{{class_with_attach_context(&mut error,previous);return Err(error);}}}}}}')
            else:dispatch.append(f'Err(error)=>{{if !({truth}){{return Err(error);}}}}')
            return '{'+setup+'match '+outcome+'{'+','.join(dispatch)+'}}'
        return emit_item(0)


def _return_value(emitter,value):
    if getattr(emitter,'context_flow_boundaries',()):return 'return Ok(ClassWithFlow::Return('+value+'))'
    return 'return Ok('+value+')'


def _loop_transfer(emitter,continuing):
    boundaries=getattr(emitter,'context_flow_boundaries',())
    if boundaries and len(emitter.loops)<=boundaries[-1]:
        return 'return Ok(ClassWithFlow::'+('Continue'if continuing else'Break')+')'
    if emitter.loops:
        from .native_loop_else import transfer
        return transfer(emitter,continuing)
    return 'unreachable!("context control contradicts lexical loop proof")'


def control_statement(emitter,node):
    if not getattr(emitter,'context_flow_boundaries',()):return None
    from .native_classes import Expression,shape
    if isinstance(node,ast.Return):
        value=Expression('()','none')if node.value is None else emitter.expression(node.value)
        return _return_value(emitter,emitter.coerce(value,shape(emitter.plan.result),node))+';'
    if isinstance(node,(ast.Break,ast.Continue))and len(emitter.loops)<=emitter.context_flow_boundaries[-1]:
        return _loop_transfer(emitter,isinstance(node,ast.Continue))+';'
    return None


def runtime(source,model):
    """Select richer error layout only for reached native cleanup regions."""
    if not model.context_managers.used:return source
    from .rust_pruning import _lex
    from .native_exception_runtime import error_record_site
    tokens,_,pairs=_lex(source);edits=[];declarations=0;constructors=0
    for index,token in enumerate(tokens[:-1]):
        if token.text!='NativeError'or tokens[index+1].text!='{':continue
        if not error_record_site(tokens,index):continue
        close=tokens[pairs[index+1]]
        prefix=''if source[:close.start].rstrip().endswith(',')else','
        if index and tokens[index-1].text=='struct':
            field='context:Option<Box<NativeError>>';declarations+=1
        else:field='context:None';constructors+=1
        edits.append((close.start,close.start,prefix+field))
    assert declarations==1 and constructors>0,(declarations,constructors)
    anchor='if let Err(error)=result {'
    start=source.rfind(anchor);assert start>=0
    opening=start+len(anchor)-1
    token_index=next(index for index,token in enumerate(tokens)if token.start==opening)
    close=tokens[pairs[token_index]]
    edits.append((opening+1,close.start,'class_with_render_error(&error);std::process::exit(1);'))
    for begin,end,text in sorted(edits,reverse=True):source=source[:begin]+text+source[end:]
    source+='''
enum ClassWithFlow<T>{Normal,Return(T),Break,Continue}
fn class_with_attach_context(error:&mut NativeError,previous:NativeError){
 let mut current=error;
 while let Some(ref mut context)=current.context{current=context;}
 current.context=Some(Box::new(previous));
}
fn class_with_render_error(error:&NativeError){
 if let Some(context)=&error.context{class_with_render_error(context);eprintln!("\\nDuring handling of the above exception, another exception occurred:\\n");}
 eprintln!("Traceback (most recent call last):");
 for &(line,function)in error.frames.iter().rev(){eprintln!("  File {:?}, line {}, in {}",function.0,line,function.1);}
 eprintln!("  File {:?}, line {}, in {}\\n{}",error.function.0,error.line,error.function.1,error.message);
}
'''
    return source
