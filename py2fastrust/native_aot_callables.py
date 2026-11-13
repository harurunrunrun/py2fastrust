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
from .references import BuiltinIdentity
from .native_module_calls import BuiltinRef
from .native_bound_methods import BoundMethodTarget


def ordered_targets(values):
    def key(value):
        if isinstance(value,BoundMethodTarget):return(3,value.definition,value.owner)
        if isinstance(value,BuiltinIdentity):return(1,value.name)
        if isinstance(value,BuiltinRef):return(2,value.module,value.name)
        return(0,value)
    return tuple(sorted(set(values),key=key))


def variant(target):
    from .native_callable_carriers import payload_type
    return payload_type(target)+'{}'


@dataclass(frozen=True)
class AotFunctionType:
    definitions: tuple[int,...]
    builtins: tuple[BuiltinIdentity,...]=()
    members: tuple[BuiltinRef,...]=()
    methods: tuple[BoundMethodTarget,...]=()
    _native_reference_cloneable=True
    _native_function_reference=True

    @property
    def _native_kind_tag(self):
        original="aot_functions_"+"_".join(map(str,self.definitions))+"_builtins_"+"_".join(value.name for value in self.builtins)+"_members_"+"_".join(value.module+"_"+value.name for value in self.members)+"_end"
        return original+("_bound_methods_"+"_".join(value._native_kind_tag if getattr(value,"_native_instance_function_target",False)else str(value.definition)for value in self.methods)+"_end"if self.methods else"")

    @property
    def targets(self):return self.definitions+self.builtins+self.members+self.methods

    @property
    def _native_owned_kinds(self):
        from .native_classes import InstanceType
        return tuple(kind for target in self.methods for kind in getattr(target,"_native_owned_kinds",(InstanceType(target.owner),)))

    @classmethod
    def from_targets(cls,targets):
        values=ordered_targets(targets)
        return cls(tuple(value for value in values if isinstance(value,int)),tuple(value for value in values if isinstance(value,BuiltinIdentity)),tuple(value for value in values if isinstance(value,BuiltinRef)),tuple(value for value in values if isinstance(value,BoundMethodTarget)))

    def join(self,other):
        return AotFunctionType.from_targets(self.targets+other.targets)


@dataclass
class CallSite:
    callee: object
    result: object
    targets: dict=field(default_factory=dict)
    errors: dict=field(default_factory=dict)
    builtins: dict=field(default_factory=dict)
    members: dict=field(default_factory=dict)
    constructors: dict=field(default_factory=dict)
    exception_constructors:dict=field(default_factory=dict)
    mapping_methods:dict=field(default_factory=dict)
    builtin_classes:dict=field(default_factory=dict)


def function_kind(kind):return isinstance(kind,AotFunctionType)


def requires_cells(unit,analysis,references=None):
    """Canonical source-function values need a runtime carrier, not erasure."""
    from .native_constraints import FunctionValue
    definitions={unit.ordinal(node)for node in unit.tree.body if isinstance(node,ast.FunctionDef)}
    bindings={binding.node:binding for binding in unit.bindings}
    names={binding.name for binding in unit.bindings if binding.role=="definition"and binding.node in definitions and binding.owner==0}
    definition_counts={}
    for definition in definitions:
        binding=bindings.get(definition)
        if binding is not None and binding.owner==0:
            definition_counts[binding.name]=definition_counts.get(binding.name,0)+1
    versioned_names={name for name,count in definition_counts.items()if count>1}
    from .native_builtin_identities import names as builtin_value_names
    SUPPORTED=builtin_value_names()
    from .native_static_builtins import capture_assignments
    static_builtin_assignments=capture_assignments(unit,analysis,references)
    if names&SUPPORTED:return True
    mutable_builtins={binding.name for binding in unit.bindings if binding.owner==0 and binding.role in {"store","delete"}and binding.name in SUPPORTED}
    if any(binding.owner==0 and binding.role=="load"and binding.name in mutable_builtins for binding in unit.bindings):return True
    if any(binding.owner==0 and binding.role=="delete"and binding.name in SUPPORTED for binding in unit.bindings):return True
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
            builtin_targets={part for part in value.alternatives if isinstance(part,BuiltinIdentity)and part.name in SUPPORTED}
            if builtin_targets:
                parent=parents.get(id(node))
                if BuiltinIdentity("globals")in builtin_targets:return True
                # A proved builtin called through its original unshadowed
                # binding keeps its existing direct adapter. Runtime callable
                # storage is needed for aliases/escapes, not builtin syntax.
                if isinstance(parent,ast.Call)and parent.func is node and all(node.id==identity.name for identity in builtin_targets):continue
                if references is not None:
                    if(caller,site)in references.static_uses:continue
                    if isinstance(parent,ast.Assign)and parent.value is node and((caller,unit.ordinal(parent))in references.assignments or(caller,unit.ordinal(parent))in static_builtin_assignments):continue
                return True
            if not targets&definitions:continue
            parent=parents.get(id(node))
            if isinstance(parent,ast.Call)and parent.func is node:
                # The existing call-only alias fastpath is complete for valid
                # fixed signatures. An invalid indirect binding still needs
                # the runtime call error after evaluating every explicit arg.
                if binding is not None and(binding.owner!=0 or binding.name not in names or binding.name in versioned_names):
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
        self.plans=dict(model.lexical.plans)
        self.definition_values={self.definition(plan):Cell("function",(self.definition(plan),))
                                for plan in model.functions.definitions.values()}
        self.definition_cells={name:self.definition_values[self.definition(plan)]for name,plan in model.functions.items()}
        self.used=set()
        self.builtin_used=set()
        self.member_used=set()
        self.member_adapters={}
        from .native_text_join import TextJoinAdapter
        self.method_adapters=[TextJoinAdapter]
        self.member_cells={}
        self.builtin_cells={}
        self.builtin_sites={}
        self.builtin_results={}
        self.fallback_names=set()
        self.sites={}
        self.receivers={}
        self.abrupt_callees=set()
        from .native_bound_methods import BoundMethods
        self.bound_methods=BoundMethods(self)
        self.function_bindings=set()
        bindings=model.unit.bindings if model.unit is not None else()
        self.mutable_names={binding.name for binding in bindings
            if model.module_owner(binding.owner) and binding.role not in {"load","parameter","definition"}}
        self.versioned_names={name for name in model.functions if len(model.function_versions(name))>1}
        self.mutable_names.update(self.versioned_names)
        self.function_bindings.update(set(model.functions)&self.mutable_names)
        from .native_builtin_identities import names as builtin_value_names
        SUPPORTED=builtin_value_names()
        self.function_bindings.update(name for name in model.functions if self.spelling(name)in SUPPORTED)
        self.used.update(self.definition(plan)for name in self.function_bindings for plan in model.function_versions(name))
        for name in model.functions:
            for plan in model.function_versions(name):
                definition=self.definition(plan)
                self.model.namespace.incoming.setdefault(name,{})[("definition",definition)]=self.definition_values[definition]

    def spelling(self,name):
        return self.model.display_name(name)

    def definition(self,plan):
        return self.model.unit.ordinal(plan.node)if self.model.unit is not None else plan.index

    def definition_value(self,node):
        return self.definition_values[self.definition(self.model.functions.definitions[node])]

    def owner(self,plan,node):
        if self.model.unit is not None:
            binding=self.model.namespace.owners.get(self.model.unit.ordinal(node))
            return None if binding is None else binding.owner
        return 0 if self.model.is_module_plan(plan) or self.model.resolved_name(plan,node)not in plan.declared else -1

    def owns_function(self,plan,node):
        name=self.model.resolved_name(plan,node)
        return name in self.model.functions and self.model.module_owner(self.owner(plan,node))

    def require_binding(self,name,node):
        self.function_bindings.add(name)
        self.model.namespace.active.add(name)
        return self.model.namespace.refresh(name,node)

    def value(self,plan,node,environment):
        if isinstance(node,ast.Name):
            lexical=self.model.lexical.function_value(plan,node,environment)
            if lexical is not None:
                self.used.update(lexical.root().args)
                return lexical
        from .native_function_body_binding_reads import read as initialized_module_read
        initialized=initialized_module_read(self,plan,node)
        if initialized is not None:return initialized
        from .native_builtin_identities import names as builtin_value_names
        SUPPORTED=builtin_value_names()
        if isinstance(node,ast.Name)and self.model.module_owner(self.owner(plan,node)):
            name=self.model.resolved_name(plan,node)
            spelling=self.spelling(name)
            if spelling in SUPPORTED:
                if name in self.model.classes:return None
                if name in self.model.global_symbols and name in(plan.visible_definitions or()):return None
                if name in self.model.global_symbols and not self.model.is_module_plan(plan) and plan.class_body is None:
                    from .native_classes import ClassUnsupported
                    raise ClassUnsupported(node,"this imported builtin-shadow binding is not definitely initialized in every call context; a namespace-owned imported-object carrier is required for runtime lookup before/after import",proof="import binding lifetime across call contexts")
                from .native_classes import Cell
                identity=BuiltinIdentity(spelling)
                from .native_type_objects import builtin_value
                special=builtin_value(self.model,identity)
                if special is None:self.builtin_used.add(identity)
                builtin=self.builtin_cells.setdefault(name,special if special is not None else Cell("function",(identity,)))
                # A declaration's identity cannot be widened by a local alias
                # phi. Keep value flow directional, as for module/default cells.
                self.model.namespace.flow_cells.add(builtin.root())
                if name in self.model.global_symbols or name not in self.mutable_names and name not in self.model.functions:
                    self.builtin_sites[(plan.index,id(node))]=identity
                    return builtin
                self.fallback_names.add(name)
                self.model.namespace.incoming.setdefault(name,{})[("builtin",name)]=builtin
                if name in self.model.functions:self.function_bindings.add(name)
                schema=self.require_binding(name,node)
                if self.model.is_module_plan(plan):
                    if name not in environment:return builtin
                    point=environment[name]
                    if name not in environment.definite:
                        joined=self.model.namespace.join_values(point,builtin,node,name,"builtin_fallback")
                        return schema if joined is None else joined
                    return point
                return schema
        if not(isinstance(node,ast.Name)and self.owns_function(plan,node)):return None
        name=self.model.resolved_name(plan,node)
        self.used.update(self.definition(target)for target in self.model.function_versions(name))
        schema=self.require_binding(name,node)
        if self.model.is_module_plan(plan) and name in environment:return environment[name]
        return schema

    def stable_direct(self,plan,node,environment=None):
        if not(isinstance(node,ast.Name)and self.owns_function(plan,node)):return False
        name=self.model.resolved_name(plan,node)
        return node.id==self.spelling(name)and name not in self.versioned_names and name not in self.mutable_names and self.spelling(name)not in self.model.namespace.builtin_names and name in(plan.visible_definitions or())

    def candidate(self,plan,node,environment):
        function=node.func
        from .native_exception_values import NAMES
        if isinstance(function,ast.Name)and function.id in NAMES and self.model.exceptions.name(plan,function,environment)is not None:return True
        from .native_builtin_singletons import canonical_kind
        if canonical_kind(self.model,plan,function,environment)is not None:return True
        if isinstance(function,ast.Name):
            name=self.model.resolved_name(plan,function)
            if name in self.versioned_names and self.owns_function(plan,function):
                return True
            if self.stable_direct(plan,function,environment):
                target=self.model.functions[name]
                if target.signature.variadic_positional:
                    try:target.signature.plan(normalize_call(node),allow_variadic=True)
                    except CallBindingError:return True
                return False
            if name in self.model.classes and self.model.module_owner(self.owner(plan,function)):return False
            current=environment.get(name)
            if current is None:current=self.model.lexical.read(plan,function,environment)
            if current is not None and current.root().tag in {"reader_text","reader_bytes","read_text","read_bytes","write_text","flush_text"}:
                # These captured standard-stream methods already have a
                # canonical intrinsic call adapter and typed read result.
                return False
            if self.spelling(name)in self.model.namespace.builtin_names and name not in self.model.functions:
                # A local/parameter binding never falls back to builtins. A
                # module binding still needs a builtin carrier after deletion.
                module_owned=self.model.module_owner(self.owner(plan,function))
                if module_owned and name in self.mutable_names:return True
                from .references import BuiltinIdentity
                identity=self.model.builtin_identity(plan,function,environment)
                if isinstance(identity,BuiltinIdentity):
                    from .native_exit import is_exit
                    if is_exit(identity):return True
                    from .native_builtin_callables import binding_error
                    try:return binding_error(identity,normalize_call(node))is not None
                    except CallBindingError:return True
                if module_owned:return False
            return True
        if isinstance(function,ast.Attribute):
            owner=self.receivers.get((plan.index,id(node)))
            if owner is None:owner=self.model.records.get((plan.index,id(function.value)))
            if owner is None:return False
            owner=owner.root()
            from .native_mapping_method_callables import supported
            from .native_classes import shape
            if all(supported(kind,function.attr)for kind in alternatives(shape(owner))):
                # Immediate popitem has its own captured-owner operation; only
                # stored method values need an allocated bound callable.
                return function.attr!='popitem'
            if self.bound_methods.finite_candidate(plan,function,owner):return True
            from .native_finite_attributes import missing_builtin
            if missing_builtin(shape(owner),function.attr):return True
            if owner.tag=="object":
                registry=getattr(self.model,'class_namespaces',None)
                if registry is not None and registry.descriptor_receiver(shape(owner),self.model.resolved_name(plan,function)):return True
                method=self.model.classes[owner.args[0]].methods.get(self.model.resolved_name(plan,function))
                if method is not None:
                    try:method.signature.plan(normalize_call(node),implicit_count=1,allow_variadic=True)
                    except CallBindingError:return True
                return method is None
            if owner.tag=="function":
                from .native_classes import shape
                if shape(owner).methods:return True
            return False
        return True

    def abrupt_callee(self,plan,node,callee):
        from .native_abrupt_values import empty,bottom
        if not empty(callee):return None
        key=plan.index,id(node)
        self.sites.pop(key,None)
        self.abrupt_callees.add(key)
        return bottom(self.model,plan,node)

    def analyze(self,plan,node,environment):
        from .native_classes import ClassUnsupported,shape
        key=plan.index,id(node)
        self.abrupt_callees.discard(key)
        self.receivers.pop(key,None)
        if isinstance(node.func,ast.Attribute):
            self.receivers[key]=self.model.expression(plan,node.func.value,environment)
            from .native_abrupt_values import attribute_operand
            abrupt=attribute_operand(self.model,plan,node.func,self.receivers[key])
            if abrupt is not None:return self.abrupt_callee(plan,node,abrupt)
        if not self.candidate(plan,node,environment):
            self.sites.pop(key,None)
            return None
        callee=(self.model.attribute_value(plan,node.func,self.receivers[key],environment)
                if isinstance(node.func,ast.Attribute)else self.model.expression(plan,node.func,environment))
        abrupt=self.abrupt_callee(plan,node,callee)
        if abrupt is not None:return abrupt
        try:arguments=normalize_call(node)
        except CallBindingError as error:
            raise ClassUnsupported(node,str(error),proof="dynamic positional/keyword argument expansion")from None
        from .native_typing_metadata import registry
        with registry(self.model).arguments(plan,callee,arguments):
            positional=[self.model.expression(plan,arg.expression,environment)for arg in arguments.positional]
            keywords=[(arg.name,self.model.expression(plan,arg.expression,environment))for arg in arguments.keywords]
        site=analyze_values(self,plan,node,callee,arguments,positional,keywords,environment)
        self.sites[(plan.index,id(node))]=site
        return self.model.remember(plan,node,site.result)

    def definition_emission(self,emitter,node):
        if not isinstance(node,ast.FunctionDef)or not self.model.is_module_plan(emitter.plan):return ""
        name=self.model.definition_name(node)
        if name not in self.function_bindings or name not in self.model.namespace.active:return ""
        index=self.model.namespace.index(name)
        target=self.model.functions.definitions[node]
        definition=self.definition(target)
        from .native_classes import Expression
        stored=dict(self.model.namespace.fields())[name]
        value=Expression(self.reference_code(emitter,target),AotFunctionType((definition,)))
        return f"class_scope.globals.borrow_mut().value_{index}=Some({emitter.coerce(value,stored,node)});"

    def reference_code(self,emitter,plan):
        from .native_callable_carriers import construct
        return construct(self,self.definition(plan))

    def lambda_reference_code(self,emitter,plan,instance):
        from .native_callable_carriers import construct
        return construct(self,self.definition(plan),instance)

    def call_pattern(self,definition,kind=None):
        from .native_callable_carriers import pattern
        return pattern(self,definition,kind or AotFunctionType((definition,)),call=True)

    def reference_pattern(self,definition,kind=None):
        from .native_callable_carriers import pattern
        return pattern(self,definition,kind or AotFunctionType((definition,)))

    def target_pattern(self,target):
        """All finite target patterns honor source reference payload hooks."""
        return self.reference_pattern(target)if isinstance(target,int)else self.bound_methods.reference_pattern(target)if isinstance(target,BoundMethodTarget)else variant(target)

    def lexical_reference_code(self,emitter,plan,owner):
        from .native_function_instances import instanced,reference
        from .native_callable_carriers import construct
        value=reference(self.model.lexical,emitter,plan,owner)if instanced(self.model.lexical,plan)else'('+owner+').clone()'
        return construct(self,self.definition(plan),value)

    def call_context_setup(self,emitter,target):return ""

    def identity(self,left,right):
        if self.bound_methods.used:return f"({left}).class_same_identity(&({right}))"
        return f"{left}=={right}"

    def runtime(self):
        from .native_callable_carriers import runtime
        return runtime(self.model)

    def register_member_adapter(self,module,adapter):
        self.member_adapters[module]=adapter

    def member_value(self,identity):
        from .native_classes import Cell
        self.member_used.add(identity)
        cell=self.member_cells.setdefault(identity,Cell("function",(identity,)))
        self.model.namespace.flow_cells.add(cell.root())
        return cell

    def reference_expression(self,identity):
        from .native_classes import Expression
        from .native_type_objects import builtin_value
        special=builtin_value(self.model,identity)
        if special is not None:return Expression(special.tag.rust,special.tag)
        if isinstance(identity,BuiltinRef):self.member_value(identity)
        else:self.builtin_used.add(identity)
        return Expression(variant(identity),AotFunctionType.from_targets((identity,)))

    def read_emission(self,emitter,node):
        from .native_classes import Expression
        identity=self.builtin_sites.get((emitter.plan.index,id(node)))
        if identity is None:return None
        from .native_type_objects import builtin_value
        special=builtin_value(self.model,identity)
        if special is not None:return Expression(special.tag.rust,special.tag)
        return Expression(variant(identity),AotFunctionType((),(identity,)))


def analyze_values(provider,plan,node,callee,arguments,positional,keywords,environment,*,identity=None):
    """Bind already produced values at a real source demand location."""
    from .native_classes import ClassUnsupported,shape
    self=provider
    result=self.model.cell(plan,node,identity=identity)
    site=CallSite(callee,result)
    kind=shape(callee)
    targets=set()
    if kind is not None:
        for branch in alternatives(kind):
            if function_kind(branch):targets.update(branch.definitions)
    from .native_builtin_callables import analyze as analyze_builtin
    from .native_module_linking import ClassReferenceType
    for branch in alternatives(kind)if kind is not None else():
        from .native_type_objects import BuiltinClass,analyze_constructor
        if isinstance(branch,BuiltinClass):
            record=analyze_constructor(self,plan,node,branch,arguments,positional,keywords,environment)
            site.builtin_classes[branch]=record
            if not self.model.namespace.contribute(result,record.result,node,force=True):self.model.contribute(result,record.result,node)
        from .native_class_stdio import CALLABLES,analyze as analyze_reader
        if branch in CALLABLES:
            value=analyze_reader(self.model,plan,node,branch,positional,keywords,
                                factory=lambda tag:self.model.cell(plan,node,tag,identity=('stdin',branch)))
            if not self.model.namespace.contribute(result,value,node,force=True):self.model.contribute(result,value,node)
        if isinstance(branch,ClassReferenceType):
            from .native_class_constructor_calls import analyze as analyze_constructor
            record=analyze_constructor(self,plan,node,branch,arguments,positional,keywords,environment,identity=identity)
            site.constructors[branch.definition]=record
            if not self.model.namespace.contribute(result,record.result,node,force=True):self.model.contribute(result,record.result,node)
        from .native_mapping_method_callables import is_method,analyze_call
        if is_method(branch):
            record=analyze_call(self.model,plan,node,branch,positional,keywords,environment,identity=identity)
            site.mapping_methods[branch]=record
            if not self.model.namespace.contribute(result,record.result,node,force=True):self.model.contribute(result,record.result,node)
        if getattr(branch,'_native_exception_class',False):
            record=self.model.exceptions.construct(plan,node,branch,positional,keywords)
            site.exception_constructors[branch]=record
            if not self.model.namespace.contribute(result,record.result,node,force=True):self.model.contribute(result,record.result,node)
        if function_kind(branch):
            for target in branch.methods:
                self.bound_methods.analyze(plan,node,target,arguments,positional,keywords,environment,site)
            for identity in branch.builtins:
                self.builtin_used.add(identity)
                value=analyze_builtin(self,plan,node,identity,arguments,positional,keywords,environment,site)
                if value is not None and not self.model.namespace.contribute(result,value,node,force=True):self.model.contribute(result,value,node)
            for identity in branch.members:
                self.member_used.add(identity)
                adapter=self.member_adapters.get(identity.module)
                if adapter is None:
                    raise ClassUnsupported(node,f"stored standard-library callable {identity.module+'.'+identity.name!r} needs its captured native member adapter; no adapter is registered",proof="canonical member callable adapter")
                factory=lambda tag=None,args=(),identity=identity:self.model.cell(plan,node,tag,args,identity=identity)
                record=adapter.analyze(self.model,plan,node,identity,arguments,positional,keywords,environment,factory=factory)
                site.members[identity]=(adapter,record)
                if not self.model.namespace.contribute(result,record.result,node,force=True):self.model.contribute(result,record.result,node)
    for definition in sorted(targets):
        target=self.plans[definition]
        self.used.add(definition)
        try:binding=target.signature.plan(arguments,allow_variadic=True)
        except CallBindingError as error:
            site.errors[definition]=binding_error(target,arguments,error)
            continue
        site.targets[definition]=binding
        value=self.model.bind_captured(plan,node,target,positional,keywords,environment)
        if not self.model.namespace.contribute(result,value,node,force=True):self.model.contribute(result,value,node)
    if self.model.final and result.root().tag is None:
        from .native_classes import Cell,merge
        if kind is None:
            raise ClassUnsupported(node,"the callee's finite callable targets remain unresolved",proof="finite current callable binding")
        merge(result,Cell("none"),node)
    return site

def binding_error(target,arguments,error,*,implicit_count=0):
    """Format the selected fixed signature's ordinary Python binding error."""
    signature=target.signature
    name=getattr(target,"qualified_name",getattr(target.node,"name","<lambda>"))+"()"
    count=len(arguments.positional)+implicit_count
    maximum=len(signature.positional)
    defaults={slot.name for slot in signature.defaults}
    # CPython processes keyword bindings before reporting excess positional
    # arguments. A positional-only keyword error is collected when the first
    # non-bindable keyword is encountered, but an earlier duplicate wins.
    supplied=set(signature.positional[:count])
    for argument in arguments.keywords:
        parameter=argument.name
        if parameter not in signature.parameters or parameter in signature.positional_only or parameter==signature.variadic_positional:
            names=[name for name in signature.positional if name in signature.positional_only
                   and any(value.name==name for value in arguments.keywords)]
            if names:
                return f"TypeError: {name} got some positional-only arguments passed as keyword arguments: {', '.join(names)!r}"
            return f"TypeError: {name} got an unexpected keyword argument {parameter!r}"
        if parameter in supplied:return f"TypeError: {name} got multiple values for argument {parameter!r}"
        supplied.add(parameter)
    if count>maximum and not signature.variadic_positional:
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
    if(emitter.plan.index,id(node))in getattr(provider,'abrupt_callees',()):
        wanted=emitter.kind(node)
        return _Expression(emitter.coerce(emitter.expression(node.func),wanted,node),wanted)
    site=provider.sites.get((emitter.plan.index,id(node)))
    if site is None:return None
    lines=[]
    from .native_immediate_classmethod import capture_callee,capture_operand,invoke
    from .native_global_callable_payload import capture as capture_global,invoke as invoke_global
    from .native_class_binding_contexts import captured_constructor
    class_constructor=captured_constructor(emitter,node,site)
    if class_constructor is not None:
        # Its exact actual class is already retained by the typed entry. The
        # class-global lookup is proved present; explicit args still follow.
        immediate=global_call=callee=None;before=''
    else:
        with capture_callee(emitter,node.func)as immediate,capture_global(emitter,node.func)as global_call:
            from .native_binding_places import capture as capture_binding
            selected=capture_operand(emitter,node,immediate)
            if selected is None:selected=capture_binding(emitter,node,global_call)
            before,callee=selected if selected is not None else emitter.capture(emitter.expression(node.func))
    lines.append(before)
    arguments=normalize_call(node)
    positional=[];keywords=[]
    for argument in arguments.positional:
        before,value=emitter.capture(emitter.expression(argument.expression));lines.append(before);positional.append(value)
    for argument in arguments.keywords:
        before,value=emitter.capture(emitter.expression(argument.expression));lines.append(before);keywords.append((argument.name,value))
    wanted=emitter.kind(node)
    if class_constructor is not None:
        from .native_class_constructor_calls import emit as emit_constructor
        return _Expression('{'+''.join(lines)+emit_constructor(emitter,node,class_constructor,None,
            positional,keywords,wanted,defining_context='class_defining_class')+'}',wanted)
    result=(invoke_global(emitter,node,global_call,site,callee,positional,keywords,wanted)
            if global_call is not None and global_call.used
            else invoke(emitter,node,immediate,site,callee,positional,keywords,wanted)
            if immediate is not None and immediate.used
            else emit_values(emitter,node,site,callee,positional,keywords,wanted))
    return _Expression("{"+''.join(lines)+result.code+"}",wanted)


def emit_definition_body(emitter,node,site,definition,positional,keywords,wanted,error,*,source_call_location=None,captured_class_context=None):
    """Bind and call an original source body in its already selected context."""
    from .native_classes import ClassUnsupported,shape
    provider=emitter.model.callable_cells
    target=provider.plans[definition]
    if definition in site.errors:return error(site.errors[definition])
    from .native_captured_invocations import bind_definition
    bound=bind_definition(emitter,node,definition,positional,keywords,captured_class_context=captured_class_context)
    return emit_bound_definition_body(emitter,node,bound,wanted,source_call_location=source_call_location)


def emit_bound_definition_body(emitter,node,bound,wanted,*,source_call_location=None):
    """Emit one already-bound original invocation, including its selected ABI."""
    target=bound.target
    from .native_source_state import bound_call
    invocation,state_output=bound_call(emitter,node,bound)
    from .native_scalar_data_results import bound_call as data_bound_call
    invocation=data_bound_call(emitter,node,target,invocation)
    from .native_class_calls import call
    from .native_source_returns import emit_result
    called=call(emitter,invocation,target,source_call_location or node)
    if state_output is not None:
        value,witness=emitter.fresh(),emitter.fresh()
        called='{let ('+value+','+witness+')='+called+';'+state_output+'='+witness+';'+value+'}'
    from .native_scalar_data_results import call_result as data_call_result
    called=data_call_result(emitter,node,invocation,called)
    return emit_result(emitter,node,target,called,wanted)


def emit_values(emitter,node,site,callee,positional,keywords,wanted,*,source_call_location=None,captured_class_context=None):
    """Invoke a captured callable without replaying any source expression."""
    from .native import _Expression,_string
    from .native_classes import ClassUnsupported,shape
    from .native_unions import project,union_kind
    provider=emitter.model.callable_cells
    def error(message):
        from .native_scalar_data_results import expected_type
        return emitter.at(f"Err::<{expected_type(emitter,node,wanted)},String>({_string(message)}.to_owned())",node)
    def branch(kind,code):
        if union_kind(kind):
            return project(kind,code,lambda child,value:branch(child,f"({value}).clone()"))
        from .native_class_stdio import CALLABLES,emit as emit_reader
        if kind in CALLABLES:
            return emit_reader(emitter,node,kind,positional,keywords,wanted).code
        from .native_type_objects import BuiltinClass,emit_constructor
        if isinstance(kind,BuiltinClass):return emit_constructor(emitter,node,kind,site.builtin_classes[kind],positional,keywords,wanted).code
        from .native_mapping_method_callables import is_method,emit_call
        if is_method(kind):return emit_call(emitter,node,kind,site.mapping_methods[kind],code,positional,keywords,wanted).code
        if getattr(kind,'_native_exception_class',False):
            record=site.exception_constructors[kind]
            return emitter.model.exceptions.emit_construct(emitter,node,record,positional,keywords,wanted).code
        if getattr(kind,'_native_cmp_key',False):
            raise ClassUnsupported(node,'calling functools.KeyWrapper outside a registered sorting-key consumer requires exposed wrapper-object construction; this native adapter currently supports captured factories in sorted and list.sort',types=(('callee',kind),),proof='exposed comparison-key object construction')
        from .native_module_linking import ClassReferenceType
        if isinstance(kind,ClassReferenceType):
            from .native_class_constructor_calls import emit as emit_constructor
            return emit_constructor(emitter,node,site.constructors[kind.definition],
                                    _Expression(code,kind),positional,keywords,wanted,
                                    source_call_location=source_call_location)
        if function_kind(kind):
            from .native_callable_carriers import dispatch,bind_payload
            def invoke_target(target,payload):
                if isinstance(target,int):
                    result=emit_definition_body(emitter,node,site,target,positional,keywords,wanted,error,source_call_location=source_call_location,captured_class_context=captured_class_context)
                    from .native_class_binding_contexts import same_function_entry
                    from .native_private_module_demands import module_unused
                    context=(''if (same_function_entry(emitter.model,emitter.plan,node,provider.plans[target])
                                   or module_unused(emitter,node,provider.plans[target]))else
                             provider.call_context_setup(emitter,provider.plans[target]))
                    return '{'+bind_payload(provider,target,payload)+context+result+'}'
                if isinstance(target,BoundMethodTarget):
                    result=provider.bound_methods.emit(emitter,node,target,site,positional,keywords,wanted,error,source_call_location=source_call_location)
                    return '{'+bind_payload(provider,target,payload)+result+'}'
                if isinstance(target,BuiltinIdentity):
                    from .native_builtin_callables import emit as emit_builtin
                    builtin=emit_builtin(emitter,node,target,site.builtins[target],positional,keywords)
                    return emitter.coerce(builtin,wanted,node)
                adapter,record=site.members[target]
                member=adapter.emit(emitter,node,target,record,positional,keywords)
                return emitter.coerce(member,wanted,node)
            return dispatch(emitter,kind,code,invoke_target)
        names={"int":"int","bool":"bool","str":"str","bytes":"bytes","float":"float","none":"NoneType","list":"list","tuple":"tuple","range":"range","builtin_singleton":"NotImplementedType"}
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
    result=emitter.fresh()
    from .native_scalar_data_results import expected_type
    actual=expected_type(emitter,node,wanted)
    request=getattr(emitter,'scalar_data_request',None)
    if request is not None and request.node is node and actual.startswith('ClassData_'):
        request.consumed=True
    return _Expression('{let '+result+':'+actual+'='+code+';'+result+'}',wanted)
