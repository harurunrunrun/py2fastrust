"""Typed, shared pull state for lazy builtin iterators on compiled frames.

Families are metadata over original source nodes. Runtime values contain only
concrete Rust payloads and cursor state; no Python operations are interpreted.
"""
import ast
from dataclasses import dataclass,field

from .call_semantics import Argument,CallArguments
from .native_types import alternatives,EMPTY,EmptyType


@dataclass(frozen=True)
class IteratorType:
    index:int
    record:object=field(compare=False,hash=False,repr=False)
    _native_reference_cloneable=True
    _native_class_iterator=True

    @property
    def _native_kind_tag(self):return "class_iterator_"+str(self.index)

    @property
    def _native_owned_kinds(self):
        from .native_classes import shape
        record=self.record
        if hasattr(record,"adapter"):return record.adapter.owned(record)
        if record.operation=="map":
            return (*record.input_types,shape(record.callback))
        if record.operation=="zip":
            return record.input_types
        if record.operation=="enumerate":return (record.input_type,)
        if record.operation=="filter":
            return (record.input_type,shape(record.callback))
        return (shape(record.source),)


@dataclass
class IteratorRecord:
    index:int
    operation:str
    node:object
    plan:object
    source:object
    element:object
    callback:object=None
    input_type:object=None
    input_types:tuple=()
    demands:dict=field(default_factory=dict)
    emitted:bool=False

    @property
    def kind(self):return IteratorType(self.index,self)


def iterator_kind(kind):return isinstance(kind,IteratorType)


def tuple_cursor_required(kind):
    from .native_types import TupleType
    return (isinstance(kind,TupleType)and len(set(kind.fields))>1 and
            not all(value in {'int','bool','int_bool'}for value in kind.fields))


class Iterators:
    def __init__(self,model):
        self.model=model
        self.records=[]
        self.sites={}

    def owns(self,kind):
        return iterator_kind(kind)and 0<=kind.index<len(self.records)and self.records[kind.index]is kind.record

    def immediate_integer_map(self,plan,node,environment):
        """Retain eager word parsing only for consumers with no saved cursor."""
        from .references import BuiltinIdentity
        tree=getattr(getattr(plan,"source_unit",None),"tree",self.model.tree)
        parents={id(child):parent for parent in ast.walk(tree)for child in ast.iter_child_nodes(parent)}
        parent=parents.get(id(node))
        if isinstance(parent,ast.Assign):
            return len(parent.targets)==1 and isinstance(parent.targets[0],(ast.Tuple,ast.List))
        return (isinstance(parent,ast.Call)and len(parent.args)==1 and not parent.keywords
                and self.model.builtin_identity(plan,parent.func,environment)==BuiltinIdentity("list"))

    def _record(self,plan,node,operation,identity=None):
        from .native_classes import Cell
        key=plan.index,id(node),operation,identity
        if key not in self.sites:
            record=IteratorRecord(len(self.records),operation,node,plan,Cell(),Cell())
            if operation in {"filter","map"}:record.callback=Cell()
            self.sites[key]=record;self.records.append(record)
        return self.sites[key]

    def _contribute(self,destination,value,node):
        if not self.model.namespace.contribute(destination,value,node,force=True):
            self.model.contribute(destination,value,node)

    def source(self,plan,node,value,identity=None):
        from .native_classes import ClassUnsupported,shape
        kind=shape(value)
        if iterator_kind(kind):return kind
        record=self._record(plan,node,"source",identity)
        self._contribute(record.source,value,node)
        root=record.source.root()
        from .native_classes import Cell
        choices=list(root.args)if root.tag=="union"else[root]
        while choices:
            choice=choices.pop()
            choice=choice.root()
            if choice.tag=="union":
                choices.extend(choice.args)
                continue
            if choice.tag in {"list","tuple","tuple_sequence","range","str","bytes"}:
                item=self.model.item(choice,node)
                if choice.tag=="tuple"and not choice.args:
                    # No Python value inhabits the immutable empty tuple.
                    item=Cell(EMPTY)
                self._contribute(record.element,item,node)
            elif self.model.mappings.views.element(shape(choice))is not None:
                self._contribute(record.element,self.model.mappings.views.element(shape(choice)),node)
            elif choice.tag is not None and all(branch in {"int","bool","int_bool","none","float"}or getattr(branch,"_native_function_reference",False)for branch in alternatives(shape(choice))):
                # Construction raises before a noniterable can yield a value.
                # It must not add a fictitious None to valid source payloads.
                self._contribute(record.element,Cell(EMPTY),node)
            elif choice.tag is not None:
                raise ClassUnsupported(node,"this iterable needs its user __iter__/__next__ or container iteration protocol; no typed pull-state adapter is registered",types=(("iterable",shape(choice)),),proof="typed iterator construction protocol")
        return record.kind

    def filter(self,plan,node,callback,source):
        from .native_classes import Cell
        record=self._record(plan,node,"filter")
        self._contribute(record.callback,callback,node)
        record.input_type=self.source(plan,node,source)
        self._contribute(record.element,record.input_type.record.element,node)
        return Cell(record.kind)

    def map(self,plan,node,callback,sources):
        from .native_classes import Cell
        record=self._record(plan,node,"map")
        self._contribute(record.callback,callback,node)
        record.input_types=tuple(self.source(plan,node,source,("map",index))
                                for index,source in enumerate(sources))
        if any(isinstance(self.model.item(Cell(kind),node).root().tag,EmptyType)
               for kind in record.input_types):
            self._contribute(record.element,Cell(EMPTY),node)
        return Cell(record.kind)

    def zip(self,plan,node,sources):
        from .native_classes import Cell
        record=self._record(plan,node,"zip")
        record.input_types=tuple(self.source(plan,node,source,("zip",index))
                                for index,source in enumerate(sources))
        if not sources:self._contribute(record.element,Cell(EMPTY),node)
        return Cell(record.kind)

    def item(self,kind):return kind.record.element

    def demand(self,plan,node,value,environment,active=()):
        from .native_classes import Cell,Environment,ClassUnsupported,shape
        if getattr(shape(value),'_native_class_generator',False):return self.model.generators.demand(plan,node,value,environment)
        if value.root().tag=="union":
            result=Cell();branches=[]
            for choice in value.root().args:
                inside=Environment(environment)
                self._contribute(result,self.demand(plan,node,choice,inside,active),node)
                branches.append(inside)
            if branches:
                joined=branches[0]
                for branch in branches[1:]:joined=self.model.join(joined,branch,node,"iterator_union")
                self.model.replace_environment(environment,joined)
            return result
        kind=shape(value)
        if value.root().tag=="enumerate":return Cell("tuple",(Cell("int"),self.demand(plan,node,value.root().args[0],environment,active)))
        if not iterator_kind(kind):return self.model.item(value,node)
        record=kind.record
        if record.index in active:
            raise ClassUnsupported(node,"recursive lazy iterator source ownership needs a recursive typed pull adapter; the finite source graph is not established",proof="finite iterator source graph")
        if hasattr(record,"adapter"):return record.adapter.demand(self,plan,node,record,environment,active)
        if record.operation in {"map","zip"}:
            items=[self.demand(plan,node,Cell(source),environment,active+(record.index,))
                   for source in record.input_types]
            if record.operation=="zip":
                if not items or any(isinstance(shape(item),EmptyType)for item in items):
                    self._contribute(record.element,Cell(EMPTY),node)
                elif all(item.root().tag is not None for item in items):
                    self._contribute(record.element,Cell("tuple",tuple(items)),node)
            elif all(item.root().tag is not None for item in items)and not any(
                    isinstance(shape(item),EmptyType)for item in items):
                from .native_aot_callables import analyze_values
                metadata=CallArguments(tuple(Argument(record.node)for _ in items),())
                site=analyze_values(self.model.callable_cells,plan,node,record.callback,
                    metadata,items,[],environment,identity=("iterator_callback",record.index))
                record.demands[(plan.index,id(node))]=site
                self._contribute(record.element,site.result,node)
        elif record.operation=="enumerate":
            from .native_enumerate import contribute_element
            item=self.demand(plan,node,Cell(record.input_type),environment,active+(record.index,))
            contribute_element(self,record,item,node)
        elif record.operation=="filter":
            self.demand(plan,node,Cell(record.input_type),environment,active+(record.index,))
            callback=record.callback
            from .native_types import alternatives
            if not isinstance(shape(record.element),EmptyType)and any(branch!="none"for branch in alternatives(shape(callback))):
                from .native_aot_callables import analyze_values
                metadata=CallArguments((Argument(record.node),),())
                inside=Environment(environment)
                site=analyze_values(self.model.callable_cells,plan,node,callback,metadata,
                    [record.element],[],inside,identity=("iterator_callback",record.index))
                record.demands[(plan.index,id(node))]=site
                self.model.replace_environment(environment,self.model.join(environment,inside,node,"iterator_callback"))
        return record.element

    def may_call(self,kind,seen=frozenset()):
        from .native_classes import shape
        if not iterator_kind(kind)or kind.index in seen:return False
        record=kind.record
        if hasattr(record,"adapter"):return record.adapter.may_call(self,record,seen)
        if record.operation=="enumerate":return self.may_call(record.input_type,seen|{kind.index})
        return record.operation=="map"or(record.operation=="zip"and any(self.may_call(source,seen|{kind.index})for source in record.input_types))or(record.operation=="filter"and(shape(record.callback)!="none"or self.may_call(record.input_type,seen|{kind.index})))

    def effects(self,plan,node):
        return any((plan.index,id(node))in record.demands for record in self.records)

    def add_lifetime_edges(self,edges,targets):
        for record in self.records:
            edges[("iterator",record.index)]={target for kind in record.kind._native_owned_kinds
                if kind is not None for target in targets(kind)}

    def snapshot(self):
        from .native_classes import shape
        return tuple((record.operation,shape(record.source),shape(record.element),
                      shape(record.callback)if record.callback is not None else None,
                      None if record.input_type is None else record.input_type.index,
                      tuple(source.index for source in record.input_types))
                     for record in self.records)

    def construct(self,emitter,node,source,*,kind=None,not_iterable=None):
        from .native_classes import Expression,ClassUnsupported,shape,domain
        kind=kind or self.sites[(emitter.plan.index,id(node),"source",None)].kind
        if iterator_kind(source.kind):return source
        record=kind.record;record.emitted=True
        tag=domain(source.kind)
        from .native_unions import project,union_kind
        if union_kind(source.kind):
            code=project(source.kind,source.code,lambda branch,code:self.construct(emitter,node,Expression(f"({code}).clone()",branch),kind=kind,not_iterable=not_iterable).code)
            return Expression(code,kind)
        if self.model.mappings.views.element(source.kind)is not None:payload=self.model.mappings.views.construct_cursor(emitter,source.kind,source.code)
        elif tag=="range":payload=source.code+".iter()"
        elif tag in {"list","tuple","tuple_sequence","str","bytes"}:payload="Some("+source.code+")"
        else:
            from .native_class_builtins import _type_name
            name=_type_name(emitter,source,node)
            error=f'format!("TypeError: \'{{}}\' object is not iterable",{name})'
            if not_iterable is not None:error=not_iterable(source)
            return Expression(emitter.at(f'Err::<ClassIterator_{record.index},String>({error})',node),kind)
        full=shape(record.source)
        if union_kind(full):
            index=alternatives(full).index(source.kind)
            payload=f"ClassIteratorSource_{record.index}::V{index}({payload})"
        return Expression(f"Rc::new(RefCell::new(ClassIteratorState_{record.index}{{source:{payload},index:0}}))",kind)

    def emit_filter(self,emitter,node,callback,source,wanted):
        from .native_classes import Expression
        record=wanted.record;record.emitted=True
        inner=self.construct(emitter,record.node,source,kind=record.input_type)
        return Expression(f"Rc::new(RefCell::new(ClassIteratorState_{record.index}{{source:{inner.code},callback:{callback.code}}}))",wanted)

    def emit_map(self,emitter,node,callback,sources,strict,wanted):
        return self.emit_multiple(emitter,node,sources,strict,wanted,callback)

    def emit_multiple(self,emitter,node,sources,strict,wanted,callback=None):
        from .native_classes import Expression
        record=wanted.record;record.emitted=True
        before=[];fields=[]
        for index,(source,kind)in enumerate(zip(sources,record.input_types)):
            setup,value=emitter.capture(self.construct(emitter,node,source,kind=kind))
            before.append(setup);fields.append(f"source_{index}:{value.code}")
        if callback is not None:fields.append("callback:"+callback.code)
        fields.append("strict:"+emitter.truth(strict))
        return Expression("{"+"".join(before)+f"Rc::new(RefCell::new(ClassIteratorState_{record.index}{{"+",".join(fields)+"}))}",wanted)

    def pull(self,emitter,node,value,active=()):
        from .native_classes import Expression
        handle=emitter.fresh()
        pulled=self._pull(emitter,node,Expression(handle,value.kind),active)
        return Expression("{let "+handle+"=&("+value.code+");"+pulled.code+"}",pulled.kind)

    def _pull(self,emitter,node,value,active=()):
        from .native_classes import ClassUnsupported,Expression,shape,domain
        kind=value.kind
        if not iterator_kind(kind):raise ClassUnsupported(node)
        record=kind.record;record.emitted=True
        if record.index in active:raise ClassUnsupported(node,"recursive iterator source pull is not yet representable",proof="finite iterator source graph")
        item_kind=shape(record.element)
        if item_kind is None:raise ClassUnsupported(node,"the iterator's element storage remains unresolved",proof="solved lazy iterator element type")
        if hasattr(record,"adapter"):return record.adapter.pull(self,emitter,node,value,active)
        if record.operation=="enumerate":
            from .native_enumerate import pull
            return pull(self,emitter,node,value,active)
        if record.operation in {"map","zip"}:return self._pull_multiple(emitter,node,value,active)
        if isinstance(item_kind,EmptyType):return Expression("None::<NativeEmpty>",item_kind)
        state=emitter.fresh();item=emitter.fresh()
        if record.operation=="filter":
            source=emitter.fresh();callback=emitter.fresh();result=emitter.fresh();decision=emitter.fresh()
            nested=self.pull(emitter,node,Expression(source,record.input_type),active+(record.index,))
            condition=self._predicate(emitter,node,record,Expression(callback,shape(record.callback)),Expression(item,item_kind))
            code=("{loop{"+f"let ({source},{callback})={{{{let {state}={value.code}.borrow();"
                  f"({state}.source.clone(),{state}.callback.clone())}}}};"
                  f"let {result}={nested.code};let Some({item})={result} else{{break None;}};"
                  f"let Some({decision})=({condition})else{{break None;}};if {decision}{{break Some({item});}}"+"}}")
            return Expression(code,item_kind)
        tag=domain(shape(record.source))
        begin="{let mut "+state+"="+value.code+".borrow_mut();"
        from .native_unions import union_kind
        if union_kind(shape(record.source)):
            old_index=emitter.fresh();advance=emitter.fresh();source=emitter.fresh()
            arms=[]
            for index,source_kind in enumerate(alternatives(shape(record.source))):
                body=self._union_source_pull(emitter,node,record,source_kind,source,old_index,item_kind)
                arms.append(f"ClassIteratorSource_{record.index}::V{index}({source})=>{body}")
            return Expression(begin+f"let {old_index}={state}.index;let ({item},{advance})=match &mut {state}.source{{"+
                ",".join(arms)+f"}};{state}.index+={advance};{item}"+"}",item_kind)
        if tag=="range":return Expression(begin+state+".source.next()}",item_kind)
        if self.model.mappings.views.element(shape(record.source))is not None:
            return Expression(begin+self.model.mappings.views.pull_cursor(emitter,node,shape(record.source),state+'.source',item_kind)+'}',item_kind)
        if tag=="tuple":
            source_kind=shape(record.source)
            arms=[]
            for index,old in enumerate(source_kind.fields):
                code=emitter.coerce(Expression(f"{state}.source.as_ref().unwrap().{index}.clone()",old),item_kind,node)
                arms.append(str(index)+"=>Some("+code+")")
            current="match "+state+".index{"+",".join(arms+["_=>None"])+"}"
        elif tag=="tuple_sequence":current=f"{state}.source.as_ref().and_then(|value|value.as_slice().get({state}.index).cloned())"
        elif tag=="list":current=f"{{{state}.source.as_ref().and_then(|value|value.borrow().get({state}.index).cloned())}}"
        elif tag=="bytes":current=f"{state}.source.as_ref().and_then(|value|value.get({state}.index)).map(|value|class_from_usize(*value as usize))"
        elif tag=="str":
            if emitter.model.string_mode=="ascii":
                current=f"{state}.source.as_ref().and_then(|value|value.as_bytes().get({state}.index)).map(|value|NativeText::from((*value as char).to_string()))"
            else:
                character=emitter.fresh()
                code=(begin+f"let {character}={state}.source.as_ref().and_then(|value|value.get({state}.index..)).and_then(|value|value.chars().next());"
                      f"if let Some({character})={character}{{{state}.index+={character}.len_utf8();Some(NativeText::from({character}.to_string()))}}else{{{state}.source=None;None}}"+"}")
                return Expression(code,item_kind)
        else:return Expression("None::<"+emitter.rust_type(item_kind)+">",item_kind)
        return Expression(begin+f"let {item}={current};if {item}.is_some(){{{state}.index+=1;}}else{{{state}.source=None;}}{item}"+"}",item_kind)

    def _pull_multiple(self,emitter,node,value,active):
        from .native_classes import Expression,shape,ClassUnsupported
        from .native_aot_callables import emit_values
        from .native import _string
        record=value.kind.record
        if not record.input_types:return Expression("None::<NativeEmpty>",EMPTY)
        state=emitter.fresh();callback=emitter.fresh();strict=emitter.fresh()
        sources=[emitter.fresh()for _ in record.input_types]
        prefix=[callback]if record.operation=="map"else[]
        stored_prefix=[state+".callback.clone()"]if record.operation=="map"else[]
        capture=",".join(prefix+[strict]+sources)
        stored=",".join(stored_prefix+[state+".strict"]+
                        [f"{state}.source_{index}.clone()"for index in range(len(sources))])
        code="{let ("+capture+")={let "+state+"="+value.code+".borrow();("+stored+")};"
        label="map_pull_"+emitter.fresh()
        code+="'"+label+":{"
        items=[]
        for index,(source,kind)in enumerate(zip(sources,record.input_types)):
            pulled=self.pull(emitter,node,Expression(source,kind),active+(record.index,))
            item=emitter.fresh();items.append(Expression(item,pulled.kind))
            if index:
                message=f"ValueError: {record.operation}() argument {index+1} is shorter than argument{'s'if index>1 else''} "+("1-"+str(index)if index>1 else"1")
                absent="if "+strict+"{"+emitter.at(f"Err::<(),String>({_string(message)}.to_owned())",node)+";}"
            else:
                checks=[]
                for other_index,(other,other_kind)in enumerate(zip(sources[1:],record.input_types[1:]),1):
                    later=self.pull(emitter,node,Expression(other,other_kind),active+(record.index,))
                    message=f"ValueError: {record.operation}() argument {other_index+1} is longer than argument{'s'if other_index>1 else''} "+("1-"+str(other_index)if other_index>1 else"1")
                    checks.append("if ("+later.code+").is_some(){"+emitter.at(f"Err::<(),String>({_string(message)}.to_owned())",node)+";}")
                absent="if "+strict+"{"+"".join(checks)+"}"
            code+="let Some("+item+")=("+pulled.code+")else{"+absent+"break '"+label+" None;};"
        if any(isinstance(item.kind,EmptyType)for item in items):
            empty=next(item for item in items if isinstance(item.kind,EmptyType))
            return Expression(code+"match "+empty.code+"{}}}",shape(record.element))
        if record.operation=="zip":
            fields=[emitter.coerce(item,wanted,node)for item,wanted in zip(items,shape(record.element).fields)]
            result=Expression("("+",".join(fields)+(","if len(fields)==1 else"")+")",shape(record.element))
        else:
            site=record.demands.get((emitter.plan.index,id(node)))
            if site is None:raise ClassUnsupported(node,"the deferred map callback has no matching typed demand proof",proof="deferred callable demand site")
            result=emit_values(emitter,node,site,Expression(callback,shape(record.callback)),items,[],shape(record.element))
        if record.operation=="map":code+=self._callback_result(emitter,result).code+"}}"
        else:code+="Some("+result.code+")}}"
        return Expression(code,shape(record.element))

    def _callback_result(self,emitter,value):
        """A callback StopIteration terminates this pull without latching it."""
        from .native_classes import Expression
        from .native_class_calls import synchronous
        result=emitter.fresh();error=emitter.fresh()
        inside='Ok::<'+emitter.rust_type(value.kind)+',NativeError>('+value.code+')'
        invocation=('(||{'+inside+'})()'if synchronous(emitter.model,emitter.plan)
                    else '(async{'+inside+'}).await')
        code=('match '+invocation+'{Ok('+result+')=>Some('+result+'),Err('+error+')=>{'
              'if '+error+'.message=="StopIteration"||'+error+'.message.starts_with("StopIteration:"){None}'
              'else{return Err('+error+');}}}')
        return Expression(code,value.kind)

    def _union_source_pull(self,emitter,node,record,kind,source,index,item_kind):
        """One concrete source alternative; no source borrow crosses a callback."""
        from .native_classes import domain,Expression
        tag=domain(kind);item=emitter.fresh()
        if self.model.mappings.views.element(kind)is not None:
            current=self.model.mappings.views.pull_cursor(emitter,node,kind,'(*'+source+')',item_kind)
            return '('+current+',0)'
        if tag=="range":current=source+".next()";advance="0"
        elif tag=="list":
            current=f"{source}.as_ref().and_then(|value|value.borrow().get({index}).cloned())";advance="1"
        elif tag=="tuple_sequence":
            current=f"{source}.as_ref().and_then(|value|value.as_slice().get({index}).cloned())";advance="1"
        elif tag=="bytes":
            current=f"{source}.as_ref().and_then(|value|value.get({index})).map(|value|class_from_usize(*value as usize))";advance="1"
        elif tag=="str":
            if emitter.model.string_mode=="ascii":
                current=f"{source}.as_ref().and_then(|value|value.as_bytes().get({index})).map(|value|NativeText::from((*value as char).to_string()))"
                advance="1"
            else:
                current=f"{source}.as_ref().and_then(|value|value.get({index}..)).and_then(|value|value.chars().next()).map(|value|NativeText::from(value.to_string()))"
                advance=f"{item}.as_ref().map_or(0,|value|value.len())"
        elif tag=="tuple":
            arms=[]
            for field,old in enumerate(kind.fields):
                code=emitter.coerce(Expression(f"{source}.as_ref().unwrap().{field}.clone()",old),item_kind,node)
                arms.append(f"{field}=>Some({code})")
            current="match "+index+"{"+",".join(arms+["_=>None"])+"}";advance="1"
            return f"{{let {item}:{'Option<'+emitter.rust_type(item_kind)+'>'}={current};if {item}.is_none(){{*{source}=None;}}({item},{advance})}}"
        else:return f"(None::<{emitter.rust_type(item_kind)}>,0)"
        old_kind=("str"if tag=="str"else"int"if tag in {"bytes","range"}else kind.element)
        converted=emitter.coerce(Expression("value",old_kind),item_kind,node)
        clear=""if tag=="range"else f"if {item}.is_none(){{*{source}=None;}}"
        return f"{{let {item}={current};let advance={advance};{clear}({item}.map(|value|{converted}),advance)}}"

    def _predicate(self,emitter,node,record,callback,item):
        from .native_classes import Expression,ClassUnsupported,shape
        from .native_unions import project,union_kind
        from .native_aot_callables import emit_values
        def branch(kind,code):
            if kind=="none":return 'Some('+emitter.truth(item)+')'
            site=record.demands.get((emitter.plan.index,id(node)))
            if site is None:raise ClassUnsupported(node,"the deferred predicate has no matching typed demand proof",proof="deferred callable demand site")
            result=emit_values(emitter,node,site,Expression("("+code+").clone()",kind),[Expression(item.code+".clone()",item.kind)],[],shape(site.result))
            temporary=emitter.fresh()
            optional=self._callback_result(emitter,result)
            return 'match '+optional.code+'{Some('+temporary+')=>Some('+emitter.truth(Expression(temporary,result.kind))+'),None=>None}'
        if union_kind(callback.kind):return project(callback.kind,callback.code,branch)
        return branch(callback.kind,callback.code)

    def runtime(self,emitter):
        from .native_classes import shape,domain,ClassUnsupported
        result=[]
        if any(record.emitted and isinstance(shape(record.element),EmptyType)for record in self.records):
            from .native_constraint_lowering import EMPTY_HELPERS
            result.append(EMPTY_HELPERS)
        # Every family has a concrete payload; aliases clone only the Rc handle.
        for record in self.records:
            if not record.emitted:continue
            if hasattr(record,"adapter"):fields=record.adapter.fields(emitter,record)
            elif record.operation in {"map","zip"}:
                fields=",".join(f"source_{index}:ClassIterator_{source.index}"for index,source in enumerate(record.input_types))
                if record.operation=="map":fields+=f",callback:{emitter.rust_type(shape(record.callback))}"
                fields+=(","if fields else"")+"strict:bool"
            elif record.operation=="enumerate":fields=f"source:ClassIterator_{record.input_type.index},index:NativeInt"
            elif record.operation=="filter":
                fields=f"source:ClassIterator_{record.input_type.index},callback:{emitter.rust_type(shape(record.callback))}"
            else:
                kind=shape(record.source);tag=domain(kind)
                from .native_unions import union_kind
                if union_kind(kind):
                    variants=[]
                    for index,choice in enumerate(alternatives(kind)):
                        payload=self.model.mappings.views.cursor_payload(emitter,choice)or("NativeRange"if domain(choice)=="range"else"Option<"+emitter.rust_type(choice)+">")
                        variants.append(f"V{index}({payload})")
                    result.append(f"enum ClassIteratorSource_{record.index}{{"+",".join(variants)+"}")
                    payload=f"ClassIteratorSource_{record.index}"
                else:payload=self.model.mappings.views.cursor_payload(emitter,kind)or("NativeRange"if tag=="range"else"Option<"+emitter.rust_type(kind)+">")
                fields=f"source:{payload},index:usize"
            result.append(f"type ClassIterator_{record.index}=Rc<RefCell<ClassIteratorState_{record.index}>>;struct ClassIteratorState_{record.index}{{{fields}}}")
        return "\n".join(result)


def requires_state(unit,analysis):
    """Stored lazy values require typed state, not an immediate stream loop."""
    from .references import BuiltinIdentity
    nodes={unit.ordinal(node):node for node in ast.walk(unit.tree)}
    parents={id(child):parent for parent in ast.walk(unit.tree)for child in ast.iter_child_nodes(parent)}
    direct={"list","tuple","sum","min","max","any","all","next","enumerate","zip"}
    from .native_stream_plans import _CONSUMERS
    identities={site:fact.identity for facts in analysis.scopes.values()for site,fact in facts.calls.items()}
    for site,fact in identities.items():
        if fact.unknown or fact.unbound or len(fact.alternatives)!=1:continue
        identity=next(iter(fact.alternatives))
        if identity not in (BuiltinIdentity("filter"),BuiltinIdentity("iter"),BuiltinIdentity("map"),BuiltinIdentity("zip"),BuiltinIdentity("enumerate")):continue
        node=nodes.get(site);parent=parents.get(id(node))
        if identity==BuiltinIdentity("enumerate"):
            if (isinstance(parent,(ast.For,ast.comprehension))and parent.iter is node
                    and 1<=len(node.args)<=2 and not node.keywords):continue
            return True
        if (isinstance(parent,ast.Assign)and len(parent.targets)==1
                and isinstance(parent.targets[0],(ast.Tuple,ast.List))):
            from .native_iterator_selection import immediate_map_unpack
            if immediate_map_unpack(unit,analysis,node,identity):continue
        if isinstance(parent,ast.For)and parent.iter is node:continue
        if isinstance(parent,ast.comprehension)and parent.iter is node:continue
        if identity==BuiltinIdentity("zip")and isinstance(parent,ast.Assign)and len(parent.targets)==1 and isinstance(parent.targets[0],(ast.Tuple,ast.List)):continue
        if isinstance(parent,ast.Call):
            caller=identities.get(unit.ordinal(parent))
            if caller is not None and not caller.unknown and not caller.unbound and len(caller.alternatives)==1:
                target=next(iter(caller.alternatives))
                immediate=direct|set(_CONSUMERS)if identity==BuiltinIdentity("zip")else direct
                if isinstance(target,BuiltinIdentity)and target.name in immediate:continue
                from .native_stream_plans import _CONSUMERS
                from .native_iterator_selection import immediate_map_unpack
                if (isinstance(target,BuiltinIdentity)and target.name in _CONSUMERS
                        and immediate_map_unpack(unit,analysis,node,identity)):continue
        return True
    return False
