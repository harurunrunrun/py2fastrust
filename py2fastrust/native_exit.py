"""Canonical termination calls using native error unwinding and typed payloads."""
from .references import BuiltinIdentity
from .native_module_calls import BuiltinRef


def is_exit(identity):
    return (isinstance(identity,BuiltinIdentity) and identity.name in {'exit','quit'}
            or isinstance(identity,BuiltinRef) and identity.module=='sys' and identity.name=='exit')


def requires_frames(analysis):
    return any(any(is_exit(value) for value in fact.identity.alternatives)
               for facts in analysis.scopes.values() for fact in facts.calls.values())


def requires_linking(program):
    # Inspect shared lexical facts; a source function named exit stays ordinary.
    import ast
    from .native_constraints import analyze
    for unit in program.units:
        if not any(isinstance(node,ast.Name)and node.id in {'exit','quit'}for node in ast.walk(unit.tree)):continue
        facts=analyze(unit)
        if requires_frames(facts)or any(any(is_exit(part)for part in value.alternatives)
                for scope in facts.scopes.values()for value in scope.values.values()):return True
    return False


def binding_error(identity,count,keywords):
    names=[name for name,_ in keywords]
    if isinstance(identity,BuiltinRef):
        if names:return 'TypeError: sys.exit() takes no keyword arguments'
        if count>1:return f'TypeError: exit expected at most 1 argument, got {count}'
    else:
        if 'self'in names:return "TypeError: Quitter.__call__() got multiple values for argument 'self'"
        unknown=next((name for name in names if name!='code'),None)
        if unknown is not None:return f"TypeError: Quitter.__call__() got an unexpected keyword argument {unknown!r}"
        if count and 'code' in names:return "TypeError: Quitter.__call__() got multiple values for argument 'code'"
        if count>1:return f'TypeError: Quitter.__call__() takes from 1 to 2 positional arguments but {count+1} were given'
    return None


def analyze(model,plan,node,identity,arguments,keywords,*,factory):
    from .native_types import EMPTY
    model.native_exit_used=True
    if not isinstance(identity,BuiltinRef):model.native_quitter_used=True
    return factory(EMPTY)


def never_returns(model,plan,node):
    """Only a completely resolved explicit call proves this abrupt edge."""
    import ast
    from .native_aot_callables import function_kind
    from .native_classes import shape
    from .native_types import alternatives
    if not isinstance(node,ast.Call):return False
    site=model.callable_cells.sites.get((plan.index,id(node)))
    if site is None:return False
    choices=alternatives(shape(site.callee))
    return bool(choices) and all(function_kind(kind) and kind.targets
            and all(is_exit(target)for target in kind.targets)for kind in choices)


def _payload_supported(kind,seen=None):
    from .native_types import alternatives,ListType,TupleType,TupleSequenceType,EmptyType
    from .native_classes import shape
    seen=set()if seen is None else seen
    if kind in seen:return True
    seen.add(kind)
    if isinstance(kind,EmptyType):return True
    for item in alternatives(kind):
        if item!=kind:
            if not _payload_supported(item,seen):return False
        elif isinstance(item,(ListType,TupleSequenceType)):
            if not _payload_supported(item.element,seen):return False
        elif isinstance(item,TupleType):
            if not all(_payload_supported(field,seen)for field in item.fields):return False
        elif getattr(item,'_native_class_mapping',False):
            if not all(_payload_supported(shape(cell),seen)for cell in (item.record.key,item.record.value)):return False
        elif item not in {'int','bool','int_bool','none','str','bytes','float'} and not getattr(item,'_native_builtin_singleton',False):return False
    return True


def emit(emitter,node,identity,arguments,keywords,wanted):
    from .native_classes import Expression,ClassUnsupported
    from .native import _string
    from .native_unions import project,union_kind
    from .native_types import EMPTY
    emitter.model.native_exit_used=True
    site=not isinstance(identity,BuiltinRef)
    if site:emitter.model.native_quitter_used=True
    error=binding_error(identity,len(arguments),keywords)
    if error:return Expression(emitter.at(f'Err::<{emitter.rust_type(wanted)},String>({_string(error)}.into())',node),wanted)
    value=arguments[0]if arguments else dict(keywords).get('code',Expression('()','none'))
    if not _payload_supported(value.kind):
        raise ClassUnsupported(node,'this exit status needs deferred Python __str__/__repr__ dispatch for its payload; native termination currently retains builtin scalar and container payloads',types=(('status',value.kind),),proof='deferred SystemExit payload display protocol')

    def lower(kind,code,context_override=None):
        payload=emitter.fresh();failure=emitter.fresh()
        value=Expression(payload,kind)
        shown=emitter.show(value,node)
        if kind=='int':
            number=f'{payload}.to_i128().and_then(|n|i64::try_from(n).ok())'if emitter.model.integer=='bigint'else f'i64::try_from({payload}).ok()'
            status=f'{number}.map(|n|n as i32).unwrap_or(-1)'
        elif kind=='bool':status=f'if {payload}{{1}}else{{0}}'
        elif kind=='int_bool':
            number=emitter.number(value)
            number=f'({number}).to_i128().and_then(|n|i64::try_from(n).ok())'if emitter.model.integer=='bigint'else f'i64::try_from({number}).ok()'
            status=f'{number}.map(|n|n as i32).unwrap_or(-1)'
        else:status='0'if kind=='none'else'1'
        printable=kind not in {'none','int','int_bool','bool'}
        # SystemExit() has no args; Quitter always raises SystemExit(code).
        context_value=(site or kind!='none')if context_override is None else context_override
        mark=f'NativeExit{{status:{status},print_payload:{str(printable).lower()},context_value:{str(context_value).lower()},render:Rc::new(move||{shown})}}'
        setup=f'let {payload}=({code}).clone();let native_exit={mark};'
        if site:setup+='class_scope.io.borrow_mut().input.closed=true;'
        setup+=f'let mut {failure}=native_at::<()>(Err(String::new()),{node.lineno},{emitter.location_code()}).unwrap_err();'
        setup+=f'{failure}.native_exit=Some(native_exit);'
        if site:
            import _sitebuiltins,dis
            function=_sitebuiltins.Quitter.__call__.__code__
            line=next(instruction.positions.lineno for instruction in dis.get_instructions(function)if instruction.opname=='RAISE_VARARGS')
            setup+=f'{failure}.frames.push(({failure}.line,{failure}.function));{failure}.line={line};{failure}.function=({_string(function.co_filename)},"__call__");'
        setup+=f'Err::<{emitter.rust_type(wanted)},NativeError>({failure})?'
        return '{'+setup+'}'
    def normalized(kind,code):
        from .native_types import TupleType,TupleSequenceType
        if not site and isinstance(kind,TupleType):
            if not kind.fields:return '{let _='+code+';'+lower('none','()',False)+'}'
            if len(kind.fields)==1:
                child=kind.fields[0];value=f'({code}).0.clone()'
                return project(child,value,lambda k,c:lower(k,c,True))if union_kind(child)else lower(child,value,True)
        if not site and isinstance(kind,TupleSequenceType):
            temporary=emitter.fresh()
            child=kind.element;value=f'{temporary}.as_slice()[0].clone()'
            one=project(child,value,lambda k,c:lower(k,c,True))if union_kind(child)else lower(child,value,True)
            return '{let '+temporary+'='+code+';match '+temporary+'.len(){0=>'+lower('none','()',False)+',1=>'+one+',_=>'+lower(kind,temporary,True)+'}}'
        return lower(kind,code)
    return Expression(project(value.kind,value.code,normalized)if union_kind(value.kind)else normalized(value.kind,value.code),wanted)


def runtime(source,model):
    if not getattr(model,'native_exit_used',False):return source
    from .rust_pruning import _lex
    from .native_exception_runtime import error_record_site
    tokens,_,pairs=_lex(source);edits=[]
    for index,token in enumerate(tokens[:-1]):
        if token.text!='NativeErrorData'or tokens[index+1].text!='{':continue
        if not error_record_site(tokens,index):continue
        close=tokens[pairs[index+1]]
        prefix=''if source[:close.start].rstrip().endswith(',')else','
        field='native_exit:Option<NativeExit>'if index and tokens[index-1].text=='struct'else'native_exit:None'
        edits.append((close.start,close.start,prefix+field))
    anchor='if let Err(error)=result {'
    start=source.rfind(anchor);assert start>=0
    edits.append((start+len(anchor),start+len(anchor),'if let Some(exit)=&error.native_exit{if exit.print_payload{eprintln!("{}",(exit.render)());}std::process::exit(exit.status);}'))
    for begin,end,text in sorted(edits,reverse=True):source=source[:begin]+text+source[end:]
    if getattr(model,'native_quitter_used',False):
        tokens,_,pairs=_lex(source);edits=[]
        for index,token in enumerate(tokens[:-1]):
            if token.text=='StandardInput'and tokens[index+1].text=='{'and index and tokens[index-1].text=='struct':
                close=tokens[pairs[index+1]]
                prefix=''if source[:close.start].rstrip().endswith(',')else','
                edits.append((close.start,close.start,prefix+'closed:bool'))
            if token.text=='StandardInputError'and index and tokens[index-1].text=='enum':
                close=tokens[pairs[index+1]];edits.append((close.start,close.start,'Closed(u8),'))
            if token.text=='native_message'and index and tokens[index-1].text=='fn':
                opening=next(i for i in range(index,len(tokens))if tokens[i].text=='match')
                brace=next(i for i in range(opening,len(tokens))if tokens[i].text=='{')
                edits.append((tokens[brace].end,tokens[brace].end,'Self::Closed(kind)=>match kind{1=>"ValueError: readline of closed file",2=>"ValueError: read of closed file",_=>"ValueError: I/O operation on closed file."}.into(),'))
            if token.text in {'read_text_into','read_binary'}and index and tokens[index-1].text=='fn':
                opening=next(i for i in range(index,len(tokens))if tokens[i].text=='{')
                binary='if line{1}else{2}'if token.text=='read_binary'else'0'
                edits.append((tokens[opening].end,tokens[opening].end,f'if self.closed{{return Err(StandardInputError::Closed({binary}));}}'))
        for begin,end,text in sorted(edits,reverse=True):source=source[:begin]+text+source[end:]
        constructor='pending:Vec::with_capacity(8196), eof:false'
        assert source.count(constructor)==1
        source=source.replace(constructor,constructor+',closed:false',1)
    # The legacy cleanup renderer has an error message field; exit payloads
    # must be rendered after cleanup, because they can retain shared lists.
    source=source.replace('error.function.1,error.message);','error.function.1,exit_context_message(&error).unwrap_or_else(||error.message.clone()));')
    source+='''
#[derive(Clone)]
struct NativeExit{status:i32,print_payload:bool,context_value:bool,render:Rc<dyn Fn()->String>}
impl std::fmt::Debug for NativeExit{fn fmt(&self,f:&mut std::fmt::Formatter<'_>)->std::fmt::Result{f.write_str("SystemExit")}}
fn exit_context_message(error:&NativeError)->Option<String>{error.native_exit.as_ref().map(|exit|if exit.context_value{format!("SystemExit: {}",(exit.render)())}else{"SystemExit".into()})}
'''
    return source
