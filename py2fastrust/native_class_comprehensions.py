"""Class-aware list materialization using the common iterable semantic plans.

The frontend's Python 3.14 symbol table inlines list-comprehension scopes.
Their target bindings still have a distinct lifetime: the first iterable runs
outside that binding scope, all later clauses run inside it, and no target
escapes. This adapter keeps those bindings separate from function frame slots.
"""
import ast
from dataclasses import dataclass, field

from .call_semantics import CallBindingError
from .native_stream_plans import Normalizer, ProducerKind, ProducerPlan
from .native_types import ListType, TupleType
from .references import BuiltinIdentity


@dataclass
class Comprehension:
    semantic: object
    bindings: dict = field(default_factory=dict)
    targets: dict = field(default_factory=dict)
    sources: tuple = ()



def target_ordinals(tree, unit):
    """Read canonical ownership of stores confined to inline comprehensions."""
    if unit is not None:
        return frozenset(binding.node for binding in unit.bindings
            if binding.role=="store"and unit.scopes[binding.owner].kind=="comprehension")
    # Model's legacy no-SourceUnit construction still receives the official AST.
    return frozenset(id(target)for node in ast.walk(tree)
        if isinstance(node,(ast.ListComp,ast.SetComp,ast.DictComp,ast.GeneratorExp))
        for clause in node.generators for target in ast.walk(clause.target)
        if isinstance(target,ast.Name)and isinstance(target.ctx,ast.Store))


def _target_names(model, plan, node):
    from .native_classes import ClassUnsupported
    if isinstance(node, ast.Name):return {model.resolved_name(plan,node)}
    if isinstance(node,ast.Starred):return _target_names(model,plan,node.value)
    if isinstance(node,(ast.Tuple,ast.List)):
        return set().union(*(_target_names(model,plan,child)for child in node.elts))
    raise ClassUnsupported(node,"comprehension targets currently require names or nested unpacking patterns; attribute and indexed target stores are not implemented by this lexical target adapter",proof="comprehension-local target binding")


def _normalizer(model, plan, environment):
    from .native import _Expression
    from .native_classes import shape
    class Context:
        def expression(self,node,values):
            return _Expression("",shape(model.expression(plan,node,values)))
    def resolve(node):
        if not isinstance(node,(ast.Name,ast.Attribute)):
            from .references import UnknownReference
            return UnknownReference(None,"this callable expression uses the captured-value adapter")
        return model.builtin_identity(plan,node,environment)
    class FrameNormalizer(Normalizer):
        def _producer(self,node):
            if isinstance(node,ast.Call):
                invocation=self.invocation(node)
                if invocation.identity in {BuiltinIdentity("iter"),BuiltinIdentity("filter"),BuiltinIdentity("map"),BuiltinIdentity("zip"),BuiltinIdentity("enumerate")}:
                    # The shared typed call binder owns callback capture,
                    # multiple sources and keywords for these stateful values.
                    return ProducerPlan(ProducerKind.VALUE,node,invocation=invocation)
            return super()._producer(node)
    return FrameNormalizer(Context(),environment,resolver=resolve)


def _bind(model, plan, target, item, environment, record):
    from .native_classes import ClassUnsupported, shape
    if isinstance(target,ast.Name):
        name=model.resolved_name(plan,target)
        binding=record.targets[id(target)]
        model.contribute(binding,item,target)
        captured=model.lexical.field_for(target)
        if captured is not None:
            model.contribute(captured[2],item,target)
            binding=captured[2]
            model.lexical.active.add(captured[0].scope)
        environment[name]=binding
        environment.definite.add(name)
        model.remember(plan,target,binding)
        return
    if isinstance(target,(ast.Tuple,ast.List)):
        from .native_class_unpacking import analyze as analyze_unpack
        if analyze_unpack(model,plan,target,item,environment,
                bind_target=lambda target,value:_bind(model,plan,target,value,environment,record)):return
        item=item.root()
        if item.tag=="tuple":
            if len(item.args)!=len(target.elts):
                raise ClassUnsupported(target,"the comprehension's fixed tuple unpacking arity differs; runtime unpacking for this typed tuple shape is not implemented",types=(("source",shape(item)),),proof="comprehension unpacking arity")
            values=item.args
        else:values=[model.item(item,target)]*len(target.elts)
        for child,value in zip(target.elts,values):
            _bind(model,plan,child,value,environment,record)
        return
    _target_names(model,plan,target)


def _register_sources(model,plan,producer,value=None):
    """Retain a proved shared cursor for finite iterable alternatives."""
    from .native_classes import shape,Cell
    from .native_unions import union_kind
    if value is None:value=model.records.get((plan.index,id(producer.node)))
    children=[_register_sources(model,plan,source)for source in producer.sources]
    if value is not None and(union_kind(shape(value))or model.iterators.needs_source_cursor(shape(value))):
        return Cell(model.iterators.source(plan,producer.node,value))
    if (value is not None and producer.kind is ProducerKind.ENUMERATE
            and value.root().tag=='enumerate'and children and children[0]is not None):
        return Cell('enumerate',(children[0],value.root().args[1]))
    return value


def analyze(model, plan, node, environment, *, contribute=None, first_value=None, semantic=None):
    """Contribute actual element/storage facts without exporting local targets."""
    from .native_classes import Cell, Environment, ClassUnsupported,shape
    key=(plan.index,id(node))
    try:semantic=semantic or _normalizer(model,plan,environment).comprehension(node)
    except CallBindingError as error:
        raise ClassUnsupported(node,str(error),proof="synchronous comprehension iteration")from None
    names=set().union(*(_target_names(model,plan,clause.target)for clause in semantic.clauses))
    record=model.comprehensions.get(key)
    if record is None:
        record=Comprehension(semantic)
        def declare(target):
            if isinstance(target,ast.Name):
                name=model.resolved_name(plan,target)
                binding=model.cell(plan,target)
                record.targets[id(target)]=binding
                record.bindings.setdefault(name,binding)
            elif isinstance(target,ast.Starred):declare(target.value)
            else:
                for child in target.elts:declare(child)
        for clause in semantic.clauses:declare(clause.target)
        model.comprehensions[key]=record
    record.semantic=semantic
    # The first iterable sees the enclosing environment, even when one of its
    # names is also a target in this or a later generator clause.
    first=semantic.clauses[0]
    if first_value is None:first_value=model.expression(plan,first.source.node,environment)
    inside=Environment(environment)
    if plan is model.module:
        # Calls still resolve their globals in the module namespace, even
        # though their argument expressions see comprehension-local bindings.
        inside.enclosing_global_names=getattr(environment,"enclosing_global_names",frozenset(environment))
    inside.update(record.bindings)
    inside.definite.difference_update(names)
    sources=[]
    for index,clause in enumerate(semantic.clauses):
        if index==0:source=first.source;value=first_value
        else:
            try:source=_normalizer(model,plan,inside).producer(clause.source.expression)
            except CallBindingError as error:
                raise ClassUnsupported(clause.source.expression,str(error),proof="typed comprehension iterable")from None
            value=model.expression(plan,source.node,inside)
        if model.iterators.needs_source_cursor(shape(value)):
            value=Cell(model.iterators.source(plan,source.node,value))
        sources.append(source)
        adapted=_register_sources(model,plan,source,value)
        _bind(model,plan,clause.target,model.iterators.demand(plan,source.node,adapted,inside),inside,record)
        for condition in clause.filters:model.condition(plan,condition,inside)
    record.sources=tuple(sources)
    if contribute is None:
        result=model.cell(plan,node,"list",(Cell(),))
        model.contribute(result.root().args[0],model.expression(plan,semantic.element,inside),semantic.element)
    else:result=contribute(inside,semantic)
    model.namespace.comprehension_effects(plan,node,environment,inside)
    return result


def read_binding(emitter, node, wanted):
    """Read a comprehension binding before the enclosing function's slots."""
    from .native_classes import Expression
    from .native import _string
    name=emitter.model.resolved_name(emitter.plan,node)
    for names,bindings in reversed(getattr(emitter,"comprehension_bindings",())):
        if name in names:
            slot=bindings[(name,wanted)]
            message=f"UnboundLocalError: cannot access local variable '{name}' where it is not associated with a value"
            return Expression(emitter.at(f"{slot}.clone().ok_or_else(||{_string(message)}.to_owned())",node),wanted)
    return None


@dataclass
class _Iterator:
    setup: str
    kind: object
    next: str


def _prepare(emitter, producer):
    """Capture one iterator once; the next expression pulls exactly one item."""
    from .native_classes import ClassUnsupported, Expression, domain, shape
    node=producer.node
    from .native_class_iterators import iterator_kind
    from .native_unions import union_kind
    registered=emitter.model.iterators.sites.get((emitter.plan.index,id(node),'source',None))
    if iterator_kind(emitter.kind(node))or registered is not None and union_kind(emitter.kind(node)):
        setup,source=emitter.capture(emitter.expression(node))
        if not iterator_kind(source.kind):
            before,source=emitter.capture(emitter.model.iterators.construct(emitter,node,source,kind=registered.kind))
            setup+=before
        value=emitter.model.iterators.pull(emitter,node,source)
        return _Iterator(setup,value.kind,value.code)
    if emitter.model.iterators.needs_source_cursor(emitter.kind(node)):
        setup,source=emitter.capture(emitter.expression(node))
        before,source=emitter.capture(emitter.model.iterators.construct(emitter,node,source));setup+=before
        value=emitter.model.iterators.pull(emitter,node,source)
        return _Iterator(setup,value.kind,value.code)
    if producer.kind is ProducerKind.ENUMERATE:
        binding=producer.binding.binding
        source=_prepare(emitter,producer.sources[0])
        start=binding["start"]
        value=(emitter.expression(start.expression)if start.expression is not None
               else Expression(emitter.literal(0),"int",0))
        if domain(value.kind)not in {"int","bool","int_bool"}:
            raise ClassUnsupported(node,"enumerate start needs an integer or a native __index__ conversion; that protocol conversion is not implemented for this value",types=(("start",value.kind),),proof="enumerate index conversion")
        before,value=emitter.capture(value)
        counter,current,saved=emitter.fresh(),emitter.fresh(),emitter.fresh()
        setup=source.setup+before+f"let mut {counter}={emitter.number(value)};"
        increment=emitter.numeric.binary(ast.Add(),Expression(counter+".clone()","int"),Expression(emitter.literal(1),"int",1),node).code
        code=f"{{match {source.next}{{Some({current})=>{{let {saved}={counter}.clone();{counter}={increment};Some(({saved},{current}))}},None=>None}}}}"
        return _Iterator(setup,TupleType(("int",source.kind)),code)
    if producer.kind is ProducerKind.MAP:
        if producer.callback!=BuiltinIdentity("int")or len(producer.sources)!=1:
            raise ClassUnsupported(node,"the class comprehension iterator only implements the proved builtin int map callback; other callback invocation/storage remains unsupported",proof="lazy map callback dispatch")
        source=_prepare(emitter,producer.sources[0]);current=emitter.fresh()
        if source.kind=="str":call=f"native_parse_integer(&{current})"
        elif source.kind=="bytes":call=f"class_parse_bytes(&{current})"
        else:raise ClassUnsupported(node,"this native map(int, ...) path requires text or bytes items",types=(("element",source.kind),),proof="per-item integer conversion")
        code=f"{{match {source.next}{{Some({current})=>Some({emitter.at(call,node)}),None=>None}}}}"
        return _Iterator(source.setup,"int",code)
    setup,source=emitter.capture(emitter.expression(node))
    tag=domain(source.kind)
    if tag=="iterator":
        value=emitter.model.iterators.pull(emitter,node,source)
        return _Iterator(setup,value.kind,value.code)
    if tag=="list":
        index,current=emitter.fresh(),emitter.fresh()
        setup+=f"let mut {index}=0_usize;"
        advance=emitter.at(f'{index}.checked_add(1).ok_or_else(||"OverflowError: list iterator index overflow".to_owned())',node)
        code=f"{{let {current}={{{source.code}.borrow().get({index}).cloned()}};if {current}.is_some(){{{index}={advance};}}{current}}}"
        return _Iterator(setup,source.kind.element,code)
    iterator=emitter.fresh()
    if tag=="range":
        return _Iterator(setup+f"let mut {iterator}={source.code}.iter();","int",f"{iterator}.next()")
    if tag=="tuple":
        item=emitter.model.item(emitter.model.records[(emitter.plan.index,id(node))],node)
        kind=shape(item)
        if kind is None:
            raise ClassUnsupported(node,"this empty tuple iteration has no solved element representation; a phantom empty-iteration value is not implemented on the class path",proof="solved comprehension iteration element type")
        values=[emitter.coerce(Expression(f"{source.code}.{i}.clone()",old),kind,node)for i,old in enumerate(source.kind.fields)]
        return _Iterator(setup+f"let mut {iterator}=["+",".join(values)+"].into_iter();",kind,f"{iterator}.next()")
    if tag=="str":
        if emitter.model.string_mode=="ascii":
            setup+=f"let mut {iterator}={source.code}.as_bytes().iter();"
            code=f"{iterator}.next().map(|value|NativeText::from((*value as char).to_string()))"
        else:
            setup+=f"let mut {iterator}={source.code}.chars();"
            code=f"{iterator}.next().map(|value|NativeText::from(value.to_string()))"
        return _Iterator(setup,"str",code)
    if tag=="bytes":
        setup+=f"let mut {iterator}={source.code}.iter();"
        return _Iterator(setup,"int",f"{iterator}.next().map(|value|class_from_usize(*value as usize))")
    raise ClassUnsupported(node,"this class comprehension iterable has no typed pull adapter; arbitrary iterator and generator protocols remain unsupported",types=(("iterable",source.kind),),proof="typed one-item iteration protocol")


def _assign(emitter, target, value, bindings):
    from .native_classes import Expression, ClassUnsupported, domain
    if isinstance(target,ast.Name):
        name=emitter.model.resolved_name(emitter.plan,target)
        kind=emitter.kind(target)
        clearing="".join(f"{slot}=None;"for(other,other_kind),slot in bindings.items()if other==name and other_kind!=kind)
        captured=emitter.model.lexical.emit_store(emitter,target,value)
        if captured is not None:return captured
        return clearing+f"{bindings[(name,kind)]}=Some({emitter.coerce(value,kind,target)});"
    if isinstance(target,(ast.Tuple,ast.List)):
        from .native_class_unpacking import emit as emit_unpack
        unpacked=emit_unpack(emitter,target,value,assign_target=lambda target,value:_assign(emitter,target,value,bindings))
        if unpacked is not None:return unpacked
        setup,source=emitter.capture(value)
        if domain(source.kind)=="tuple":
            if len(source.kind.fields)!=len(target.elts):raise ClassUnsupported(target)
            values=[Expression(f"{source.code}.{i}.clone()",kind)for i,kind in enumerate(source.kind.fields)]
        elif domain(source.kind)=="tuple_sequence":
            setup+=emitter.at(f"class_tuple_unpack_length({source.code}.len(),{len(target.elts)})",target)+";"
            values=[Expression(f"{source.code}.as_slice()[{i}].clone()",source.kind.element)for i in range(len(target.elts))]
        elif domain(source.kind)=="list":
            unpack=emitter.fresh()
            setup+=f"let {unpack}={emitter.at(f'class_unpack(&{source.code},{len(target.elts)})',target)};"
            values=[Expression(f"{unpack}[{i}].clone()",source.kind.element)for i in range(len(target.elts))]
        else:raise ClassUnsupported(target,"this comprehension unpacking source needs a generic iterator-unpack adapter",types=(("source",source.kind),),proof="ordered comprehension target unpacking")
        return setup+"".join(_assign(emitter,child,item,bindings)for child,item in zip(target.elts,values))
    raise ClassUnsupported(target)


@dataclass(frozen=True)
class Collector:
    initialize: object
    append: object
    finish: object


def prepare_first(emitter,node):
    """Capture the original first iterable before a consumer's later operands."""
    record=emitter.model.comprehensions[(emitter.plan.index,id(node))]
    return _prepare(emitter,record.sources[0])


def emit(emitter, node, *, collector=None, first=None, wanted=None, owned=False):
    from .native_classes import Expression, shape
    record=emitter.model.comprehensions[(emitter.plan.index,id(node))]
    wanted=emitter.kind(node)if wanted is None else wanted
    # Generate/capture the first source before installing the target namespace.
    first=prepare_first(emitter,node)if first is None else first
    bindings={}
    def declare(target):
        if isinstance(target,ast.Name):
            key=emitter.model.resolved_name(emitter.plan,target),emitter.kind(target)
            if key not in bindings:bindings[key]=emitter.fresh()
        elif isinstance(target,ast.Starred):declare(target.value)
        else:
            for child in target.elts:declare(child)
    for clause in record.semantic.clauses:declare(clause.target)
    lexical_setup,lexical_context=emitter.model.lambda_cells.comprehension_initialize(emitter,node)
    contexts=getattr(emitter,"comprehension_environments",None)
    if contexts is None:contexts={};emitter.comprehension_environments=contexts
    previous_context=contexts.get(lexical_context[0])if lexical_context is not None else None
    if lexical_context is not None:contexts[lexical_context[0]]=lexical_context[1]
    declarations="".join(f"let mut {slot}:Option<{emitter.rust_type(kind)}>=None;"for(name,kind),slot in bindings.items())
    result=emitter.fresh()
    scopes=getattr(emitter,"comprehension_bindings",None)
    if scopes is None:scopes=[];emitter.comprehension_bindings=scopes
    scopes.append((set(record.bindings),bindings))
    try:
        def loop(index):
            clause=record.semantic.clauses[index]
            source=first if index==0 else _prepare(emitter,record.sources[index])
            current=emitter.fresh()
            body=_assign(emitter,clause.target,Expression(current,source.kind),bindings)
            for condition in clause.filters:
                before,value=emitter.capture(emitter.condition(condition))
                body+=before+f"if !({emitter.truth(value)}){{continue;}}"
            if index+1<len(record.sources):body+=loop(index+1)
            elif collector is not None:
                body+=collector.append(emitter,result,record.semantic)
            else:
                before,value=emitter.capture(emitter.expression(record.semantic.element))
                reserve=emitter.at(f'{result}.try_reserve(1).map_err(|_|"MemoryError: cannot allocate list".to_owned())',node)
                body+=before+reserve+";"+f"{result}.push({emitter.coerce(value,wanted.element,record.semantic.element)});"
            setup=""if index==0 else source.setup
            return setup+f"while let Some({current})={source.next}{{{body}}}"
        initial=(f"let mut {result}:Vec<{emitter.rust_type(wanted.element)}>=Vec::new();"if collector is None
                 else collector.initialize(emitter,result,wanted))
        finish=(result if owned else f"class_list({result})")if collector is None else collector.finish(emitter,result,wanted)
        code=first.setup+lexical_setup+declarations+initial+loop(0)+finish
    finally:
        scopes.pop()
        if lexical_context is not None:
            if previous_context is None:contexts.pop(lexical_context[0])
            else:contexts[lexical_context[0]]=previous_context
    return Expression("{"+code+"}",wanted)
