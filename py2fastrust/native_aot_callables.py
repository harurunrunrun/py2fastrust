"""Finite AOT function references and direct typed Rust call dispatch.

A descriptor copies a reference identity, never a function object's mutable
state. Target IDs are official SourceUnit definition ordinals. Arguments are
normalized/captured once after capturing the current callee, then a Rust match
enters the resolved compiled function. There is no instruction interpreter.
"""
import ast
from dataclasses import dataclass,field

from .call_semantics import CallBindingError,normalize_call
from .native_types import alternatives,union_type


@dataclass(frozen=True)
class AotFunctionType:
    definitions: tuple[int,...]
    _native_reference_cloneable=True
    _native_function_reference=True

    @property
    def _native_kind_tag(self):
        return "aot_functions_"+"_".join(map(str,self.definitions))+"_end"

    def join(self,other):
        return AotFunctionType(tuple(sorted(set(self.definitions)|set(other.definitions))))


@dataclass
class CallSite:
    callee: object
    result: object
    targets: dict=field(default_factory=dict)
    errors: dict=field(default_factory=dict)


def function_kind(kind):return isinstance(kind,AotFunctionType)


def requires_cells(unit,analysis,references=None):
    """Canonical source-function values need a runtime carrier, not erasure."""
    from .native_constraints import FunctionValue
    definitions={unit.ordinal(node)for node in unit.tree.body if isinstance(node,ast.FunctionDef)}
    bindings={binding.node:binding for binding in unit.bindings}
    names={binding.name for binding in unit.bindings if binding.role=="definition"and binding.node in definitions and binding.owner==0}
    # A module write can replace the original definition even when its saved
    # aliases themselves are call-only. Do not erase that module-cell lifetime.
    def module_execution(scope):
        while scope is not None and unit.scopes[scope].kind=="comprehension":scope=unit.scopes[scope].parent
        return scope==0
    if any(binding.owner==0 and module_execution(binding.scope)and binding.name in names
           and binding.role in {"store","delete"}for binding in unit.bindings):return True
    nodes={unit.ordinal(node):node for node in ast.walk(unit.tree)}
    parents={id(child):parent for parent in ast.walk(unit.tree)for child in ast.iter_child_nodes(parent)}
    for (caller,_),facts in analysis.scopes.items():
        for site,value in facts.values.items():
            node=nodes.get(site)
            if not isinstance(node,ast.Name):continue
            binding=bindings.get(site)
            if value.unbound and binding is not None and binding.owner==0 and binding.name in names:return True
            targets={part.definition for part in value.alternatives if isinstance(part,FunctionValue)}
            if not targets&definitions:continue
            parent=parents.get(id(node))
            if isinstance(parent,ast.Call)and parent.func is node:
                # The existing call-only alias fastpath is complete for valid
                # fixed signatures. An invalid indirect binding still needs
                # the runtime call error after evaluating every explicit arg.
                if binding is not None and(binding.owner!=0 or binding.name not in names):
                    for definition in targets&definitions:
                        try:unit.signature_for(nodes[definition]).plan(normalize_call(parent))
                        except CallBindingError:return True
                continue
            if isinstance(parent,ast.Assign)and parent.value is node and references is not None:
                if(caller,unit.ordinal(parent))in references.assignments:continue
            return True
    return False


class CallableCells:
    enabled=True

    def __init__(self,model):
        from .native_classes import Cell
        self.model=model
        self.plans={self.definition(plan):plan for plan in model.functions.values()}
        self.definition_cells={name:Cell("function",(self.definition(plan),))for name,plan in model.functions.items()}
        self.used=set()
        self.sites={}
        self.function_bindings=set()
        bindings=model.unit.bindings if model.unit is not None else()
        self.mutable_names={binding.name for binding in bindings
            if binding.owner==0 and binding.role not in {"load","parameter","definition"}}
        self.function_bindings.update(set(model.functions)&self.mutable_names)
        self.used.update(self.definition(model.functions[name])for name in self.function_bindings)
        for name,plan in model.functions.items():
            self.model.namespace.incoming.setdefault(name,{})[("definition",self.definition(plan))]=self.definition_cells[name]

    def definition(self,plan):
        return self.model.unit.ordinal(plan.node)if self.model.unit is not None else plan.index

    def owner(self,plan,node):
        if self.model.unit is not None:
            binding=self.model.namespace.owners.get(self.model.unit.ordinal(node))
            return None if binding is None else binding.owner
        return 0 if plan is self.model.module or self.model.resolved_name(plan,node)not in plan.declared else -1

    def owns_function(self,plan,node):
        name=self.model.resolved_name(plan,node)
        return name in self.model.functions and self.owner(plan,node)==0

    def require_binding(self,name,node):
        self.function_bindings.add(name)
        self.model.namespace.active.add(name)
        return self.model.namespace.refresh(name,node)

    def value(self,plan,node,environment):
        if not(isinstance(node,ast.Name)and self.owns_function(plan,node)):return None
        name=self.model.resolved_name(plan,node)
        if name in self.model.namespace.builtin_names and(name in self.mutable_names or name not in(plan.visible_definitions or())):
            from .native_classes import ClassUnsupported
            raise ClassUnsupported(node,"this function name can require a first-class builtin fallback; builtin-object callable carriers and restoration after deletion remain required but are not implemented",proof="module/function/builtin callable identity")
        self.used.add(self.definition(self.model.functions[name]))
        return self.require_binding(name,node)

    def stable_direct(self,plan,node,environment=None):
        if not(isinstance(node,ast.Name)and self.owns_function(plan,node)):return False
        name=self.model.resolved_name(plan,node)
        return node.id==name and name not in self.mutable_names and name in(plan.visible_definitions or())

    def candidate(self,plan,node,environment):
        function=node.func
        if isinstance(function,ast.Name):
            name=self.model.resolved_name(plan,function)
            if self.stable_direct(plan,function,environment):return False
            if name in self.model.classes and self.owner(plan,function)==0:return False
            current=environment.get(name)
            if current is not None and current.root().tag in {"reader_text","reader_bytes","read_text","read_bytes"}:
                # These captured standard-stream methods already have a
                # canonical intrinsic call adapter and typed read result.
                return False
            if name in self.model.namespace.builtin_names and name not in self.model.functions:
                # A local/parameter binding never falls back to builtins. A
                # module binding still needs a builtin carrier after deletion.
                if self.owner(plan,function)==0:return False
                from .references import BuiltinIdentity
                if isinstance(self.model.builtin_identity(plan,function,environment),BuiltinIdentity):return False
            return True
        if isinstance(function,ast.Attribute):
            owner=self.model.expression(plan,function.value,environment).root()
            if owner.tag=="object":
                method=self.model.classes[owner.args[0]].methods.get(self.model.resolved_name(plan,function))
                return method is None
            return False
        return True

    def analyze(self,plan,node,environment):
        from .native_classes import ClassUnsupported,shape
        if not self.candidate(plan,node,environment):return None
        try:arguments=normalize_call(node)
        except CallBindingError as error:
            raise ClassUnsupported(node,str(error),proof="dynamic positional/keyword argument expansion")from None
        callee=self.model.expression(plan,node.func,environment)
        positional=[self.model.expression(plan,arg.expression,environment)for arg in arguments.positional]
        keywords=[(arg.name,self.model.expression(plan,arg.expression,environment))for arg in arguments.keywords]
        result=self.model.cell(plan,node)
        site=CallSite(callee,result)
        self.sites[(plan.index,id(node))]=site
        kind=shape(callee)
        targets=set()
        if kind is not None:
            for branch in alternatives(kind):
                if function_kind(branch):targets.update(branch.definitions)
        for definition in sorted(targets):
            target=self.plans[definition]
            self.used.add(definition)
            try:binding=target.signature.plan(arguments)
            except CallBindingError as error:
                site.errors[definition]=binding_error(target,arguments,error)
                continue
            site.targets[definition]=binding
            value=self.model.bind_call(plan,node,target,positional,keywords,environment)
            if not self.model.namespace.contribute(result,value,node,force=True):self.model.contribute(result,value,node)
        if self.model.final and result.root().tag is None:
            from .native_classes import Cell,merge
            if kind is None:
                raise ClassUnsupported(node,"the callee's finite callable targets remain unresolved",proof="finite current callable binding")
            merge(result,Cell("none"),node)
        return self.model.remember(plan,node,result)

    def definition_emission(self,emitter,node):
        if not isinstance(node,ast.FunctionDef)or emitter.plan is not self.model.module:return ""
        name=node.name
        if name not in self.function_bindings:return ""
        index=self.model.namespace.index(name)
        definition=self.definition(self.model.functions[name])
        from .native_classes import Expression
        stored=dict(self.model.namespace.fields())[name]
        value=Expression(f"ClassFunctionRef::F{definition}",AotFunctionType((definition,)))
        return f"class_scope.globals.borrow_mut().value_{index}=Some({emitter.coerce(value,stored,node)});"

    def runtime(self):
        if not self.used:return ""
        definitions=sorted(self.used)
        return "#[derive(Clone,Copy,PartialEq,Eq)]\nenum ClassFunctionRef{"+",".join(f"F{value}"for value in definitions)+"}\n"


def binding_error(target,arguments,error):
    """Format the selected fixed signature's ordinary Python binding error."""
    signature=target.signature
    name=target.node.name+"()"
    count=len(arguments.positional)
    maximum=len(signature.positional)
    defaults={slot.name for slot in signature.defaults}
    # CPython processes keyword bindings before reporting excess positional
    # arguments. A positional-only keyword error is collected when the first
    # non-bindable keyword is encountered, but an earlier duplicate wins.
    supplied=set(signature.positional[:count])
    for argument in arguments.keywords:
        parameter=argument.name
        if parameter not in signature.parameters or parameter in signature.positional_only:
            names=[name for name in signature.positional if name in signature.positional_only
                   and any(value.name==name for value in arguments.keywords)]
            if names:
                return f"TypeError: {name} got some positional-only arguments passed as keyword arguments: {', '.join(names)!r}"
            return f"TypeError: {name} got an unexpected keyword argument {parameter!r}"
        if parameter in supplied:return f"TypeError: {name} got multiple values for argument {parameter!r}"
        supplied.add(parameter)
    if count>maximum:
        minimum=sum(parameter not in defaults for parameter in signature.positional)
        quantity=(str(maximum)if minimum==maximum else f"from {minimum} to {maximum}")
        noun="argument"if maximum==1 and minimum==maximum else"arguments"
        kwcount=sum(argument.name in signature.keyword_only for argument in arguments.keywords)
        if kwcount:
            extra=(f"{count} positional argument{''if count==1 else's'} "
                   f"(and {kwcount} keyword-only argument{''if kwcount==1 else's'}) were")
        else:extra=f"{count} {'was'if count==1 else'were'}"
        return f"TypeError: {name} takes {quantity} positional {noun} but {extra} given"
    text=str(error)
    if text.startswith("unexpected keyword argument: "):
        return f"TypeError: {name} got an unexpected keyword argument {text.split(': ',1)[1]!r}"
    if text.startswith("multiple values for argument: "):
        return f"TypeError: {name} got multiple values for argument {text.split(': ',1)[1]!r}"
    if text.startswith("positional-only argument passed by keyword: "):
        names=[argument.name for argument in arguments.keywords if argument.name in signature.positional_only]
        return f"TypeError: {name} got some positional-only arguments passed as keyword arguments: {', '.join(names)!r}"
    if text.startswith("missing required argument: "):
        missing=[parameter for parameter in signature.positional if parameter not in supplied and parameter not in defaults]
        keyword=False
        if not missing:
            missing=[parameter for parameter in signature.keyword_only if parameter not in supplied and parameter not in defaults]
            keyword=True
        quoted=[repr(parameter)for parameter in missing]
        joined=quoted[0]if len(quoted)==1 else" and ".join(quoted)if len(quoted)==2 else", ".join(quoted[:-1])+", and "+quoted[-1]
        category="keyword-only"if keyword else"positional"
        return f"TypeError: {name} missing {len(missing)} required {category} argument{''if len(missing)==1 else's'}: {joined}"
    return f"TypeError: {name} {text}"


def emit_call(emitter,node):
    from .native import _Expression,_string
    from .native_classes import ClassUnsupported,Emitter,shape
    from .native_unions import project,union_kind
    provider=emitter.model.callable_cells
    site=provider.sites.get((emitter.plan.index,id(node)))
    if site is None:return None
    lines=[]
    before,callee=emitter.capture(emitter.expression(node.func));lines.append(before)
    arguments=normalize_call(node)
    positional=[];keywords=[]
    for argument in arguments.positional:
        before,value=emitter.capture(emitter.expression(argument.expression));lines.append(before);positional.append(value)
    for argument in arguments.keywords:
        before,value=emitter.capture(emitter.expression(argument.expression));lines.append(before);keywords.append((argument.name,value))
    wanted=emitter.kind(node)
    def error(message):
        return emitter.at(f"Err::<{emitter.rust_type(wanted)},String>({_string(message)}.to_owned())",node)
    def branch(kind,code):
        if union_kind(kind):
            return project(kind,code,lambda child,value:branch(child,f"({value}).clone()"))
        if function_kind(kind):
            arms=[]
            for definition in kind.definitions:
                target=provider.plans[definition]
                if definition in site.errors:result=error(site.errors[definition])
                else:
                    default_emitter=Emitter(emitter.model,target)
                    try:bound=target.signature.bind(positional,keywords,default_emitter.captured_defaults(target))
                    except CallBindingError as failure:raise ClassUnsupported(node,str(failure))from None
                    values=[emitter.coerce(value,shape(target.arguments[name]),node)for name,value in zip(bound.parameters,bound.values)]
                    invocation=emitter.function_name(target)+"(class_scope.clone()"+(","+",".join(values)if values else"")+")"
                    from .native_class_calls import call
                    result=emitter.coerce(_Expression(call(emitter,invocation,target,node),shape(target.result)),wanted,node)
                arms.append(f"ClassFunctionRef::F{definition}=>{result}")
            if set(kind.definitions)!=provider.used:
                arms.append('_=>unreachable!("callable binding contradicts finite target proof")')
            return "match "+code+"{"+",".join(arms)+"}"
        names={"int":"int","bool":"bool","str":"str","bytes":"bytes","float":"float","none":"NoneType","list":"list","tuple":"tuple","range":"range"}
        from .native_classes import domain
        tag=domain(kind)
        if tag=="object":name=emitter.model.classes[kind.name].node.name
        elif tag=="int_bool":
            return f"match {code}{{NativeScalar::Int(_)=>"+error("TypeError: 'int' object is not callable")+",NativeScalar::Bool(_)=>"+error("TypeError: 'bool' object is not callable")+"}"
        else:name=names.get(tag)
        if name is None:
            raise ClassUnsupported(node,"this callable alternative needs an object/builtin call protocol not yet implemented",types=(("callee",kind),),proof="callable-object protocol")
        return error(f"TypeError: '{name}' object is not callable")
    code=branch(callee.kind,callee.code)
    return _Expression("{"+''.join(lines)+code+"}",wanted)
