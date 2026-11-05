"""Capture exact global source-callable payloads before explicit arguments."""
import ast
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass(frozen=True)
class Layout:
    definition:int
    environment_type:str|None=None

    @property
    def rust_type(self):
        return 'ClassModuleRef'if self.environment_type is None else '('+self.environment_type+',ClassModuleRef)'

    def borrowed_pattern(self):
        from .native_callable_carriers import payload_type
        fields='module:class_payload_module'if self.environment_type is None else'environment:class_payload_environment,module:class_payload_module'
        return payload_type(self.definition)+'{'+fields+'}'

    def cloned(self):
        if self.environment_type is None:return 'class_payload_module.clone()'
        return '(class_payload_environment.clone(),class_payload_module.clone())'

    def unpack(self,code):
        names='class_defining_module'if self.environment_type is None else'(class_selected_environment,class_defining_module)'
        return 'let '+names+'='+code+';'


def linked_layout(provider,definition):
    plan=provider.plans.get(definition)
    if plan is None or not plan.reachable or not isinstance(plan.node,(ast.FunctionDef,ast.Lambda)):return None
    parent=provider.model.lexical.parent_scope(plan)
    environment=None
    if isinstance(plan.node,ast.Lambda):
        environment='Rc<'+provider.model.lambda_cells.payload_type(plan)+'>'
    elif parent:
        from .native_function_instances import instanced,reference_type
        environment=(reference_type(provider.model.lexical,plan)if instanced(provider.model.lexical,plan)
                     else'Rc<'+provider.model.lexical.environment_type(parent)+'>')
    return Layout(definition,environment)


def metadata_observed(model):
    cached=getattr(model,'global_callable_metadata_observed',None)
    if cached is not None:return cached
    from .native_classes import shape
    from .native_aot_callables import AotFunctionType
    result=set()
    for plan in model.plans:
        if not plan.reachable:continue
        for node in ast.walk(plan.node):
            if not isinstance(node,ast.Attribute):continue
            cell=model.records.get((plan.index,id(node.value)))
            if cell is not None:
                kind=shape(cell)
                if isinstance(kind,AotFunctionType):result.update(kind.definitions)
    model.global_callable_metadata_observed=frozenset(result)
    return model.global_callable_metadata_observed


@dataclass
class Request:
    node:object
    name:str
    slot:int
    layout:Layout
    used:bool=False


def candidate(emitter,node):
    if not isinstance(node,ast.Name)or emitter.model.unit is None:return None
    from .native_aot_callables import AotFunctionType
    from .native_class_calls import synchronous
    kind=emitter.kind(node)
    if not isinstance(kind,AotFunctionType)or len(kind.targets)!=1 or type(kind.targets[0])is not int:return None
    definition=kind.targets[0];provider=emitter.model.callable_cells
    if (definition not in provider.plans or not synchronous(emitter.model,emitter.plan)
            or not synchronous(emitter.model,provider.plans[definition])
            or getattr(emitter,'iterator_callback_context',None)is not None):return None
    namespace=emitter.model.namespace
    name=emitter.model.resolved_name(emitter.plan,node)
    if name not in namespace.active or not namespace.owns(emitter.plan,node)or name in provider.fallback_names:return None
    if dict(namespace.fields()).get(name)!=kind or definition in metadata_observed(emitter.model):return None
    describe=getattr(provider,'call_payload_layout',None)
    layout=None if describe is None else describe(definition)
    if layout is None:return None
    # A complete exact payload can be empty after source demand analysis.
    # The old accessor returns module/environment fields specifically; use
    # the ordinary exact typed namespace read for the new physical schema.
    from .native_callable_carriers import registry
    carrier=registry(emitter.model)
    if carrier.layout(definition).fields!=carrier.logical_layout(definition).fields:return None
    return Request(node,name,namespace.index(name),layout)


@contextmanager
def capture(emitter,node):
    previous=getattr(emitter,'global_callable_request',None)
    request=candidate(emitter,node)
    emitter.global_callable_request=request
    try:yield request
    finally:emitter.global_callable_request=previous


def read(emitter,node,wanted):
    request=getattr(emitter,'global_callable_request',None)
    if request is None or request.node is not node:return None
    from .native_classes import Expression
    registry=getattr(emitter.model,'global_callable_payload_accessors',None)
    if registry is None:
        registry={};emitter.model.global_callable_payload_accessors=registry
    registry[(request.slot,request.layout.definition)]=request
    request.used=True
    code=f'class_global_payload_{request.slot}_{request.layout.definition}(&class_scope)'
    return Expression(emitter.at(code,node),wanted)


def invoke(emitter,node,request,site,callee,positional,keywords,wanted):
    from .native import _Expression,_string
    from .native_aot_callables import emit_definition_body
    provider=emitter.model.callable_cells
    def error(message):
        return emitter.at('Err::<'+emitter.rust_type(wanted)+',String>('+_string(message)+'.to_owned())',node)
    body=emit_definition_body(emitter,node,site,request.layout.definition,positional,keywords,wanted,error)
    from .native_class_binding_contexts import same_function_entry
    context=(''if same_function_entry(emitter.model,emitter.plan,node,provider.plans[request.layout.definition])else
             provider.call_context_setup(emitter,provider.plans[request.layout.definition]))
    return _Expression('{'+request.layout.unpack(callee.code)+context+body+'}',wanted)


def runtime(model):
    from .native import _string
    declarations=[]
    for (slot,definition),request in sorted(getattr(model,'global_callable_payload_accessors',{}).items()):
        assert slot==model.namespace.index(request.name)
        layout=request.layout
        message=_string("NameError: name '"+model.display_name(request.name)+"' is not defined")
        captured='class_payload_value.module.clone()'
        if layout.environment_type is not None:captured='(class_payload_value.environment.clone(),'+captured+')'
        code=(f'fn class_global_payload_{slot}_{definition}(scope:&ClassScope)->Result<{layout.rust_type},String>{{'
              f'let class_payload_globals=scope.globals.borrow();'
              f'let class_payload_value=class_payload_globals.value_{slot}.as_ref().ok_or_else(||{message}.to_owned())?;'
              'Ok('+captured+')}')
        declarations.append(code)
    return '\n'.join(declarations)
