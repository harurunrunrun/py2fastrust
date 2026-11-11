"""Owned eager word snapshots with lazy canonical integer conversion."""
import ast
from dataclasses import dataclass

from .references import BuiltinIdentity


@dataclass(frozen=True)
class IntegerWordMap:
    source:object
    source_kind:str

    def owned(self,record):return (self.source_kind,)

    def demand(self,registry,plan,node,record,environment,active):return record.element

    def may_call(self,registry,record,seen):return False

    def fields(self,emitter,record):
        return f'source:{emitter.rust_type(self.source_kind)},words:Vec<(usize,usize)>,index:usize'

    def pull(self,registry,emitter,node,value,active):
        from .native_classes import Expression,shape
        state,first,length,word=(emitter.fresh()for _ in range(4))
        view=f'{state}.source.as_str()'if self.source_kind=='str'else f'{state}.source.as_slice()'
        parse='class_parse_text'if self.source_kind=='str'else'class_parse_bytes'
        parsed=emitter.at(f'{parse}({word})',node)
        code=('{'+f'let mut {state}=({value.code}).borrow_mut();'
              f'if let Some(({first},{length}))={state}.words.get({state}.index).copied(){{'
              f'{state}.index+=1;let {word}=&({view})[{first}..{first}+{length}];Some({parsed})'
              '}else{None}}')
        return Expression(code,shape(value.kind.record.element))


def prepare(model):
    """Select storage only after the shared value/call solution is complete."""
    from .native_classes import shape
    from .native_class_iterators import iterator_kind
    for record in model.iterators.records:
        if record.operation!='map'or len(record.input_types)!=1:continue
        node=record.node;plan=record.plan
        if not isinstance(node,ast.Call)or len(node.args)!=2 or any(isinstance(a,ast.Starred)for a in node.args):continue
        if any(keyword.arg!='strict'for keyword in node.keywords):continue
        result=model.records.get((plan.index,id(node)))
        if result is None or shape(result)!=record.kind:continue
        callback=shape(record.callback)
        if not getattr(callback,'_native_function_reference',False)or callback.targets!=(BuiltinIdentity('int'),):continue
        site=model.callable_cells.sites.get((plan.index,id(node)))
        if site is not None:
            if site.targets or site.members or set(site.builtins)!={BuiltinIdentity('map')}:continue
        elif not(isinstance(node.func,ast.Name)and node.func.id=='map'
                 and model.resolved_name(plan,node.func)not in plan.declared
                 and 'map'not in model.global_written_names):continue
        source=node.args[1]
        if not isinstance(source,ast.Call)or not isinstance(source.func,ast.Attribute):continue
        if (plan.index,id(source))not in getattr(model,'text_split_sites',{}):continue
        receiver=model.records.get((plan.index,id(source.func.value)))
        if receiver is None or shape(receiver)not in {'str','bytes'}:continue
        record.adapter=IntegerWordMap(source,shape(receiver))


def emit_call(emitter,node):
    from .native_classes import Expression
    from .native_class_iterators import iterator_kind
    from .call_semantics import normalize_call
    kind=emitter.kind(node)
    direct=emit_immediate_list(emitter,node,kind)
    if direct is not None:return direct
    if not iterator_kind(kind):return None
    record=kind.record;adapter=getattr(record,'adapter',None)
    if not isinstance(adapter,IntegerWordMap)or record.node is not node:return None
    record.emitted=True
    setup=''
    # Even a statically proved identity keeps its actual binding read and error.
    for expression in (node.func,node.args[0]):
        # An unshadowed direct builtin has no stored callable expression. Its
        # namespace identity was proved by prepare; saved aliases keep reads.
        if (emitter.plan.index,id(expression))not in emitter.model.records:continue
        setup+='let _='+emitter.expression(expression).code+';'
    source=adapter.source
    before,receiver=emitter.capture(emitter.expression(source.func.value));setup+=before
    positional=[];keywords={}
    for argument in normalize_call(source).evaluation_order:
        before,value=emitter.capture(emitter.expression(argument.expression));setup+=before
        if argument.name is None:positional.append(value)
        else:keywords[argument.name]=value
    def collect(source_kind,text,cursor,reverse):
        words,part,base=(emitter.fresh()for _ in range(3))
        view=f'({text}).as_str()'if source_kind=='str'else f'({text}).as_slice()'
        reserve=emitter.at(f'{words}.try_reserve(1).map_err(|_|"MemoryError: cannot allocate split words".to_owned())',source)
        return ('{'+f'let {base}=({view}).as_ptr()as usize;let mut {words}=Vec::<(usize,usize)>::new();'
                f'for {part} in {cursor}{{{reserve};{words}.push(({part}.as_ptr()as usize-{base},{part}.len()));}}'
                +(f'{words}.reverse();'if reverse else'')+
                f'Rc::new(RefCell::new(ClassIteratorState_{record.index}{{source:{text},words:{words},index:0}}))'+'}')
    from .native_class_splits import emit
    snapshot=emit(emitter,source,receiver,positional,keywords,kind,collector=collect)
    before,snapshot=emitter.capture(snapshot);setup+=before
    for keyword in node.keywords:
        before,value=emitter.capture(emitter.expression(keyword.value));setup+=before
        setup+='let _='+emitter.truth(value)+';'
    return Expression('{'+setup+snapshot.code+'}',kind)


def parse_immediate(emitter,node,count=None,*,consumer=None,shared=False):
    """Fuse a proved immediate map_int source without allocating text words."""
    from .native_classes import domain
    from .native_types import ListType
    from .call_semantics import normalize_call
    if domain(emitter.kind(node))!='map_int'or not isinstance(node,ast.Call)or len(node.args)!=2:return None
    if any(keyword.arg!='strict'for keyword in node.keywords):return None
    source=node.args[1]
    if not isinstance(source,ast.Call)or not isinstance(source.func,ast.Attribute):return None
    if (emitter.plan.index,id(source))not in getattr(emitter.model,'text_split_sites',{}):return None
    receiver_kind=emitter.kind(source.func.value)
    if receiver_kind not in {'str','bytes'}:return None
    consumer=consumer or node
    setup=''
    for expression in (node.func,node.args[0]):
        if (emitter.plan.index,id(expression))in emitter.model.records:
            setup+='let _='+emitter.expression(expression).code+';'
    before,receiver=emitter.capture(emitter.expression(source.func.value));setup+=before
    positional=[];keywords={}
    for argument in normalize_call(source).evaluation_order:
        before,value=emitter.capture(emitter.expression(argument.expression));setup+=before
        if argument.name is None:positional.append(value)
        else:keywords[argument.name]=value
    wanted=ListType('int')
    stack=count is not None and count<=32 and not shared
    def map_options():
        code=''
        for keyword in node.keywords:
            before,value=emitter.capture(emitter.expression(keyword.value));code+=before
            code+='let _='+emitter.truth(value)+';'
        return code
    def collect(kind,text,cursor,reverse):
        words,part,base,values,first,length,word=(emitter.fresh()for _ in range(7))
        view=f'({text}).as_str()'if kind=='str'else f'({text}).as_slice()'
        parse='class_parse_text'if kind=='str'else'class_parse_bytes'
        if stack:
            size=count+1
            total,start=emitter.fresh(),emitter.fresh()
            body=(f'let {base}=({view}).as_ptr()as usize;'
                f'let mut {words}:[Option<(usize,usize)>;{size}]=std::array::from_fn(|_|None);'
                f'let mut {total}=0_usize;')
            if reverse:body+=f'let mut {start}=0_usize;'
            body+=(f'for {part} in {cursor}{{if {total}<{size}{{'
                f'{words}[{total}]=Some(({part}.as_ptr()as usize-{base},{part}.len()));{total}+=1;}}')
            if reverse:
                body+=(f'else{{{words}[{start}]=Some(({part}.as_ptr()as usize-{base},{part}.len()));'
                    f'{start}=({start}+1)%{size};}}')
            body+='}'+map_options()
            body+=f'let mut {values}:[Option<NativeInt>;{count}]=std::array::from_fn(|_|None);'
            index=emitter.fresh()
            position=(f'if {index}<{total}{{{words}[({start}+{total}-1-{index})%{size}]}}else{{None}}'
                if reverse else f'{words}[{index}]')
            position=emitter.at('('+position+f').ok_or_else(||format!("ValueError: not enough values to unpack (expected {count}, got {{}})",{index}))',consumer)
            parsed=emitter.at(f'{parse}({word})',consumer)
            body+=(f'for {index} in 0..{count}{{let ({first},{length})={position};'
                f'let {word}=&({view})[{first}..{first}+{length}];{values}[{index}]=Some({parsed});}}')
            extra_position=(f'{words}[({start}+{total}-1-{count})%{size}]'if reverse else f'{words}[{count}]')
            extra=emitter.at(f'Err::<(),String>("ValueError: too many values to unpack (expected {count})".to_owned())',consumer)
            body+=(f'if {total}>{count}{{let ({first},{length})=({extra_position}).unwrap();'
                f'let {word}=&({view})[{first}..{first}+{length}];let _={parsed};{extra};}}')
            return '{'+body+f'{values}.map(Option::unwrap)'+'}'
        reserve=emitter.at(f'{words}.try_reserve(1).map_err(|_|"MemoryError: cannot allocate split words".to_owned())',source)
        body=(f'let {base}=({view}).as_ptr()as usize;let mut {words}=Vec::<(usize,usize)>::new();'
              f'for {part} in {cursor}{{{reserve};{words}.push(({part}.as_ptr()as usize-{base},{part}.len()));}}')
        if reverse:body+=f'{words}.reverse();'
        body+=map_options()
        limit=f'{words}.len()'if count is None else str(count)
        body+=f'let mut {values}=Vec::<NativeInt>::new();'
        body+=emitter.at(f'{values}.try_reserve_exact({limit}).map_err(|_|"MemoryError: cannot allocate integers".to_owned())',consumer)+';'
        parsed=emitter.at(f'{parse}({word})',consumer)
        if count is None:
            body+=f'for ({first},{length})in {words}{{let {word}=&({view})[{first}..{first}+{length}];{values}.push({parsed});}}'
        else:
            index=emitter.fresh()
            position=emitter.at(f'{words}.get({index}).copied().ok_or_else(||format!("ValueError: not enough values to unpack (expected {count}, got {{}})",{index}))',consumer)
            body+=f'for {index} in 0..{count}{{let ({first},{length})={position};let {word}=&({view})[{first}..{first}+{length}];{values}.push({parsed});}}'
            extra=emitter.at(f'Err::<(),String>("ValueError: too many values to unpack (expected {count})".to_owned())',consumer)
            body+=f'if let Some(({first},{length}))={words}.get({count}).copied(){{let {word}=&({view})[{first}..{first}+{length}];let _={parsed};{extra};}}'
        return '{'+body+(f'class_list({values})'if shared else values)+'}'
    from .native_class_splits import emit
    result=emit(emitter,source,receiver,positional,keywords,wanted,collector=collect,
        result_rust_type=f'[NativeInt;{count}]'if stack else None if shared else 'Vec<NativeInt>')
    code='{'+setup+result.code+'}'
    return code


def emit_immediate_list(emitter,node,wanted):
    from .native_classes import Expression
    from .native_types import ListType
    if wanted!=ListType('int')or len(node.args)!=1 or node.keywords:return None
    site=emitter.model.callable_cells.sites.get((emitter.plan.index,id(node)))
    if site is not None:
        if site.targets or site.members or set(site.builtins)!={BuiltinIdentity('list')}:return None
    elif not(isinstance(node.func,ast.Name)and node.func.id=='list'
             and emitter.model.resolved_name(emitter.plan,node.func)not in emitter.plan.declared
             and 'list'not in emitter.model.global_written_names):return None
    if isinstance(node.args[0],ast.Starred):return None
    fused=parse_immediate(emitter,node.args[0],consumer=node,shared=True)
    if fused is None:return None
    setup=''
    if (emitter.plan.index,id(node.func))in emitter.model.records:setup+='let _='+emitter.expression(node.func).code+';'
    return Expression('{'+setup+fused+'}',wanted)
