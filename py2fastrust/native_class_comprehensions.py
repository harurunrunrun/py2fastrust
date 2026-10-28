"""Class-aware list materialization using the common iterable semantic plans.

The frontend's Python 3.14 symbol table inlines list-comprehension scopes.
Their target bindings still have a distinct lifetime: the first iterable runs
outside that binding scope, all later clauses run inside it, and no target
escapes. This adapter keeps those bindings separate from function frame slots.
"""
import ast
from dataclasses import dataclass, field

from .call_semantics import CallBindingError
from .native_stream_plans import Normalizer, ProducerKind
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
    if isinstance(node,(ast.Tuple,ast.List)):
        return set().union(*(_target_names(model,plan,child)for child in node.elts))
    raise ClassUnsupported(node,"comprehension targets currently require names or fixed unpacking patterns; starred, attribute and index target protocols are not implemented",proof="comprehension-local target binding")


def _normalizer(model, plan, environment):
    from .native import _Expression
    from .native_classes import shape
    class Context:
        def expression(self,node,values):
            return _Expression("",shape(model.expression(plan,node,values)))
    return Normalizer(Context(),environment,
        resolver=lambda node:model.builtin_identity(plan,node,environment))


def _bind(model, plan, target, item, environment, record):
    from .native_classes import ClassUnsupported, shape
    if isinstance(target,ast.Name):
        name=model.resolved_name(plan,target)
        binding=record.targets[id(target)]
        model.contribute(binding,item,target)
        environment[name]=binding
        environment.definite.add(name)
        model.remember(plan,target,binding)
        return
    if isinstance(target,(ast.Tuple,ast.List)):
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


def analyze(model, plan, node, environment):
    """Contribute actual element/storage facts without exporting local targets."""
    from .native_classes import Cell, Environment, ClassUnsupported
    key=(plan.index,id(node))
    try:semantic=_normalizer(model,plan,environment).comprehension(node)
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
            else:
                for child in target.elts:declare(child)
        for clause in semantic.clauses:declare(clause.target)
        model.comprehensions[key]=record
    record.semantic=semantic
    # The first iterable sees the enclosing environment, even when one of its
    # names is also a target in this or a later generator clause.
    first=semantic.clauses[0]
    first_value=model.expression(plan,first.source.node,environment)
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
        sources.append(source)
        _bind(model,plan,clause.target,model.item(value,source.node),inside,record)
        for condition in clause.filters:model.condition(plan,condition,inside)
    record.sources=tuple(sources)
    result=model.cell(plan,node,"list",(Cell(),))
    model.contribute(result.root().args[0],model.expression(plan,semantic.element,inside),semantic.element)
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
        return clearing+f"{bindings[(name,kind)]}=Some({emitter.coerce(value,kind,target)});"
    if isinstance(target,(ast.Tuple,ast.List)):
        setup,source=emitter.capture(value)
        if domain(source.kind)=="tuple":
            if len(source.kind.fields)!=len(target.elts):raise ClassUnsupported(target)
            values=[Expression(f"{source.code}.{i}.clone()",kind)for i,kind in enumerate(source.kind.fields)]
        elif domain(source.kind)=="list":
            unpack=emitter.fresh()
            setup+=f"let {unpack}={emitter.at(f'class_unpack(&{source.code},{len(target.elts)})',target)};"
            values=[Expression(f"{unpack}[{i}].clone()",source.kind.element)for i in range(len(target.elts))]
        else:raise ClassUnsupported(target,"this comprehension unpacking source needs a generic iterator-unpack adapter",types=(("source",source.kind),),proof="ordered comprehension target unpacking")
        return setup+"".join(_assign(emitter,child,item,bindings)for child,item in zip(target.elts,values))
    raise ClassUnsupported(target)


def emit(emitter, node):
    from .native_classes import Expression, shape
    record=emitter.model.comprehensions[(emitter.plan.index,id(node))]
    wanted=emitter.kind(node)
    # Generate/capture the first source before installing the target namespace.
    first=_prepare(emitter,record.sources[0])
    bindings={}
    def declare(target):
        if isinstance(target,ast.Name):
            key=emitter.model.resolved_name(emitter.plan,target),emitter.kind(target)
            if key not in bindings:bindings[key]=emitter.fresh()
        else:
            for child in target.elts:declare(child)
    for clause in record.semantic.clauses:declare(clause.target)
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
            else:
                before,value=emitter.capture(emitter.expression(record.semantic.element))
                reserve=emitter.at(f'{result}.try_reserve(1).map_err(|_|"MemoryError: cannot allocate list".to_owned())',node)
                body+=before+reserve+";"+f"{result}.push({emitter.coerce(value,wanted.element,record.semantic.element)});"
            setup=""if index==0 else source.setup
            return setup+f"while let Some({current})={source.next}{{{body}}}"
        code=first.setup+declarations+f"let mut {result}:Vec<{emitter.rust_type(wanted.element)}>=Vec::new();"+loop(0)+f"class_list({result})"
    finally:scopes.pop()
    return Expression("{"+code+"}",wanted)
