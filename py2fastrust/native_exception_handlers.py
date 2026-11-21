"""Native try/except/else/finally regions on the framed path.

The protected body runs in a Rust closure (or async block) whose result keeps
normal completion, return, break, continue and the raised error apart. A raised
error is matched against canonical builtin exception classes by its Python
class name, including every builtin subclass. Handler, else and finally code
reuses the same flow encoding, so a later error retains its implicit context.
"""
import ast
import builtins
from dataclasses import dataclass


_TERMINATION=frozenset({'SystemExit','KeyboardInterrupt','GeneratorExit'})


def _classes():
    result={}
    for value in vars(builtins).values():
        if isinstance(value,type)and issubclass(value,BaseException):result[value.__name__]=value
    return result


_CLASSES=_classes()


def covered_names(name):
    """Builtin exception class names caught by an ``except name`` clause."""
    base=_CLASSES[name]
    return frozenset(other for other,value in _CLASSES.items()if issubclass(value,base))


@dataclass
class Handler:
    node: ast.ExceptHandler
    names: frozenset|None


def _handler_names(model,plan,handler,environment):
    from .native_classes import ClassUnsupported
    from .references import BuiltinIdentity,UnboundReference
    if handler.type is None:return None
    items=handler.type.elts if isinstance(handler.type,ast.Tuple)else[handler.type]
    names=set()
    for item in items:
        reference=model.builtin_identity(plan,item,environment)if isinstance(item,ast.Name)else None
        canonical=isinstance(reference,BuiltinIdentity)or isinstance(reference,UnboundReference)and not reference.local
        spelling=model.display_name(reference.name)if canonical else None
        if spelling not in _CLASSES:
            raise ClassUnsupported(item,'this except clause names a value that is not a proved canonical builtin exception class; matching user-defined or runtime-selected exception classes is not implemented',operation='exception handler type',proof='canonical builtin exception class identity')
        linker=getattr(model,'module_linker',None)
        if linker is not None and 'builtins'in linker.modules:
            key=model.unit.global_name('builtins',spelling)
            if key in model.namespace.incoming or key in model.namespace.active:
                raise ClassUnsupported(item,'this exception-class read may observe a modified builtins namespace; mutable exception-class matching is not implemented',proof='unmodified canonical exception class')
        if spelling=='BaseException':return None
        if spelling in _TERMINATION:
            raise ClassUnsupported(item,'catching process termination or interruption needs native SystemExit/KeyboardInterrupt objects; only Exception subclasses are matched natively',operation='exception handler type',proof='native termination exception objects')
        names|=covered_names(spelling)
    return frozenset(names-_TERMINATION)


def analyze(model,plan,node,environment):
    """Return the continuation environment of one try statement."""
    from .native_classes import ClassUnsupported,Environment
    if isinstance(node,getattr(ast,'TryStar',())):
        raise ClassUnsupported(node,'except* needs native exception groups and split matching; that protocol is not implemented',proof='exception group splitting')
    for child in ast.walk(node):
        if isinstance(child,(ast.Yield,ast.YieldFrom,ast.Await)):
            raise ClassUnsupported(child,'a suspension inside a try statement needs a resumable protected region; that generator/coroutine frame layout is not implemented',proof='resumable exception-handler region')
    for handler in node.handlers:
        if handler.name is not None:_text_only_binding(model,handler)
    for statement in node.finalbody:
        for child in ast.walk(statement):
            if isinstance(child,(ast.Return,ast.Break,ast.Continue)):
                raise ClassUnsupported(child,'control transfer from a finally clause discards the pending exception or result; that override is not implemented',proof='finally-clause control override')
    model.exceptions.require(node)
    model.native_exception_handlers_used=True
    states=[Environment(environment)]
    current=environment
    for statement in node.body:
        current=model.block(plan,[statement],current)
        if current is None:break
        states.append(Environment(current))
    normal=model.block(plan,node.orelse,current)if current is not None and node.orelse else current
    exceptional=None
    for state in states:exceptional=model.join(exceptional,state,node,'exception_handler_entry')
    handlers=[];outcome=normal
    for handler in node.handlers:
        names=_handler_names(model,plan,handler,exceptional)
        if names is None and getattr(model,'native_exit_used',False):
            raise ClassUnsupported(handler,'this catch-all handler would also catch SystemExit raised by exit(); native termination exception objects are not implemented',proof='native SystemExit matching')
        entry=Environment(exceptional)
        if handler.name is not None:model.bind_name(plan,handler,model.cell(plan,handler,'str'),entry)
        finished=model.block(plan,handler.body,entry)
        handlers.append(Handler(handler,names))
        outcome=model.join(outcome,finished,node,'exception_handler_exit')
    if node.finalbody:
        # The single finally body runs after normal completion, handlers and
        # every propagating exit, so it is analyzed for all of those entries.
        entry=model.join(outcome,exceptional,node,'finally_entry')
        finished=model.block(plan,node.finalbody,entry)
        outcome=None if outcome is None or finished is None else finished
    sites=getattr(model,'native_exception_handler_sites',None)
    if sites is None:sites=model.native_exception_handler_sites={}
    sites[(plan.index,id(node))]=handlers
    return outcome


def _region(emitter,code,result_type):
    # Rust may not see every abrupt native call as diverging, so the region
    # always ends with normal completion; the crate allows unreachable code.
    from .native_class_calls import synchronous
    body=code+'Ok(ClassWithFlow::Normal)'
    flow=f'ClassResult<ClassWithFlow<{result_type}>>'
    if synchronous(emitter.model,emitter.plan):return f'(||->{flow}{{{body}}})()'
    return f'(async{{{body}}}).await'


def _protected(emitter,statements,result_type,bind=None):
    boundaries=getattr(emitter,'context_flow_boundaries',None)
    if boundaries is None:boundaries=emitter.context_flow_boundaries=[]
    boundaries.append(len(emitter.loops))
    try:
        code=''
        if bind is not None:
            # str(error): the message after "Name: ", or empty without arguments.
            from .native_classes import Expression
            handler,error=bind
            text=('NativeText::from(match '+error+'.message.find(": "){Some(index)=>'+error+'.message[index+2..].to_owned(),None=>String::new()})')
            code=emitter.assign_name(handler,Expression(text,'str'))
        code+=emitter.statements(statements)
    finally:boundaries.pop()
    return _region(emitter,code,result_type)


def _match(error,names):
    if names is None:return 'true'
    if not names:return 'false'
    return f'matches!({error}.message.split(\':\').next().unwrap_or(""),'+'|'.join('"'+name+'"'for name in sorted(names))+')'


def emit(emitter,node):
    from .native_classes import shape
    from .native_context_managers import _return_value,_loop_transfer
    handlers=emitter.model.native_exception_handler_sites[(emitter.plan.index,id(node))]
    result_type=emitter.rust_type(shape(emitter.plan.result))
    flow=f'ClassResult<ClassWithFlow<{result_type}>>'
    attach='class_exception_attach_context'
    outcome,error,previous,raised,value=(emitter.fresh()for _ in range(5))
    lines=[f'let {outcome}:{flow}={_protected(emitter,node.body,result_type)};']
    orelse=(_protected(emitter,node.orelse,result_type)
            if node.orelse else'Ok(ClassWithFlow::Normal)')
    branches=[]
    for handler in handlers:
        region=_protected(emitter,handler.node.body,result_type,
                          bind=None if handler.node.name is None else(handler.node,previous))
        branches.append(f'if {_match(error,handler.names)}{{let {previous}={error};match {region}{{Err(mut {raised})=>{{{attach}(&mut {raised},{previous});Err({raised})}},{value}=>{value}}}}}')
    dispatch='else '.join(branches+[f'{{Err({error})}}'])if branches else f'Err({error})'
    lines.append(f'let {outcome}:{flow}=match {outcome}{{Ok(ClassWithFlow::Normal)=>{orelse},Ok({value})=>Ok({value}),Err({error})=>{dispatch}}};')
    if node.finalbody:
        final=emitter.fresh()
        region=_protected(emitter,node.finalbody,result_type)
        lines.append(f'let {final}:{flow}={region};')
        lines.append(f'let {outcome}:{flow}=match {final}{{Ok(_)=>{outcome},Err(mut {raised})=>{{if let Err({previous})={outcome}{{{attach}(&mut {raised},{previous});}}Err({raised})}}}};')
    lines.append(f'match {outcome}{{Ok(ClassWithFlow::Normal)=>(),Ok(ClassWithFlow::Return({value}))=>{_return_value(emitter,value)},'
                 f'Ok(ClassWithFlow::Break)=>{_loop_transfer(emitter,False)},Ok(ClassWithFlow::Continue)=>{_loop_transfer(emitter,True)},'
                 f'Err({error})=>return Err({error})}}')
    return '{'+''.join(lines)+'}'


def runtime(model):
    if not getattr(model,'native_exception_handlers_used',False)or model.context_managers.used:return ''
    return 'enum ClassWithFlow<T>{Normal,Return(T),Break,Continue}\n'


def _text_only_binding(model,handler):
    """Admit `except E as name` when only str(name) is observable.

    Every use of the name is inside the body of a handler that binds the same
    name (this one or a sibling, never nested in another) as a positional
    print() argument, str(name) or a plain f-string field, and nothing else in
    the module reads, writes or deletes it, so the implicit unbinding at each
    handler end and the exception object's identity are unobservable.
    """
    from .native_classes import ClassUnsupported
    unit=model.unit
    try:key=unit.name_for(handler)
    except KeyError:key=None
    reason=None
    def bound_here(other):
        if not isinstance(other,ast.ExceptHandler)or other.name is None:return False
        try:return unit.name_for(other)==key
        except KeyError:return False
    handlers=[other for other in ast.walk(model.tree)if key is not None and bound_here(other)]
    inside=set()
    for other in handlers:
        body={id(child)for statement in other.body for child in ast.walk(statement)}
        if any(id(nested)in body for nested in handlers):reason='a nested handler rebinds the name'
        inside|=body
    parents={}
    for parent in ast.walk(model.tree):
        for child in ast.iter_child_nodes(parent):parents[id(child)]=parent
    for item in ast.walk(model.tree):
        if reason is not None:break
        if not isinstance(item,ast.Name)or key is None:continue
        try:resolved=unit.name_for(item)
        except KeyError:continue
        if resolved!=key:continue
        parent=parents.get(id(item))
        if id(item)not in inside or not isinstance(item.ctx,ast.Load):reason='the name is used outside its handler';break
        printed=(isinstance(parent,ast.Call)and isinstance(parent.func,ast.Name)and parent.func.id=='print'and item in parent.args)
        converted=(isinstance(parent,ast.Call)and isinstance(parent.func,ast.Name)and parent.func.id=='str'and parent.args==[item]and not parent.keywords)
        formatted=isinstance(parent,ast.FormattedValue)and parent.conversion in(-1,115)and parent.format_spec is None
        if not(printed or converted or formatted):reason='the caught object is used beyond its str() text';break
    if key is None:reason='the handler name has no resolved binding'
    if reason is not None:
        raise ClassUnsupported(handler,'binding the caught exception object needs native exception values; only print(), str() and f-string text of the name is implemented and '+reason,
                               operation='exception handler name binding',proof='caught exception object')
