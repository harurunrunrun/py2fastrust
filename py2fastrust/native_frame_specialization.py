"""Native body instances retain the original Python callable identity.

Source templates own signatures, defaults and captured module/lexical state.
An instance owns only its typed arguments/result/locals and native call graph
position. Original AST nodes and shared semantic heap constraints are reused.
"""
import ast
from dataclasses import replace


MAX_CONTEXTS=16


def source_plan(plan):
    return getattr(plan,'specialization_source',plan)


def _polymorphic(kind):
    from .native_types import UnionType,NullableType,TupleType
    if kind=='int_bool'or isinstance(kind,(UnionType,NullableType)):return True
    return isinstance(kind,TupleType)and any(_polymorphic(field)for field in kind.fields)


def _closed_carrier(kind,*,result=False):
    from .native_classes import InstanceType
    from .native_types import TupleType,UnionType,NullableType
    if kind in {'int','bool','float','str','bytes','none'}or isinstance(kind,InstanceType):return True
    if isinstance(kind,TupleType):return all(_closed_carrier(field,result=result)for field in kind.fields)
    if result and isinstance(kind,UnionType):return all(_closed_carrier(field,result=True)for field in kind.alternatives)
    if result and isinstance(kind,NullableType):return _closed_carrier(kind.value,result=True)
    return False


class Specializations:
    def __init__(self,model):
        self.model=model
        self.enabled=False
        self.templates={}
        self.instances={}
        self.reasons={}

    def enable(self):
        """Select candidates from the complete original semantic fixed point."""
        from .native_classes import shape
        model=self.model
        if model.unit is None:return
        for plan in tuple(model.plans):
            if not plan.reachable or model.is_module_plan(plan)or plan.class_body is not None:continue
            if not isinstance(plan.node,ast.FunctionDef)or plan.node.name=='__init__':continue
            if plan.node.decorator_list or getattr(plan.node,'type_params',()):
                self.reasons[plan.index]='decorated/generic function metadata keeps its canonical source ABI'
                continue
            if plan.signature.variadic_positional or plan.signature.variadic_keyword:continue
            if getattr(plan,'erased_context_parameters',()):continue
            scope=model.lexical.scope(plan)
            own=model.lexical.environments.get(scope)
            if model.lexical.parent_scope(plan)is not None or own is not None:
                self.reasons[plan.index]='source lexical environment/captured cells need their canonical joined ABI'
                continue
            if any(isinstance(node,(ast.Lambda,ast.GeneratorExp,ast.Yield,ast.YieldFrom))
                   or node is not plan.node and isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))
                   for node in ast.walk(plan.node)):
                self.reasons[plan.index]='nested callable/generator state retains the existing native plan'
                continue
            if not any(_polymorphic(shape(value))for value in plan.arguments.values()):continue
            if not _closed_carrier(shape(plan.result),result=True):
                self.reasons[plan.index]='mutable/opaque return storage keeps its shared original ABI'
                continue
            self.templates[plan.index]=plan
        self.enabled=bool(self.templates)

    def _key(self,source,bound):
        from .native_classes import shape
        source=source_plan(source)
        if not self.enabled or source.index not in self.templates:return None
        kinds=tuple(getattr(value,'kind',None)if not hasattr(value,'root')else shape(value)
                    for value in(bound[name]for name in source.runtime_parameters))
        if not all(_closed_carrier(kind)for kind in kinds):return None
        return source.index,kinds

    def select(self,source,bound,*,create):
        from .native_classes import Cell
        source=source_plan(source)
        key=self._key(source,bound)
        if key is None:return source
        existing=self.instances.get(key)
        if existing is not None:return existing
        if not create or self.model.final:return source
        if sum(owner==source.index for owner,_ in self.instances)>=MAX_CONTEXTS:
            return source
        # Do not duplicate source signatures/default/capture ownership or
        # semantic member/heap cells. Only frame-local typing is instantiated.
        instance=replace(source,index=len(self.model.plans),
            arguments={name:Cell()for name in source.arguments},result=Cell(),locals={},
            declared=set(source.declared),
            reachable=False,global_names=None,visible_definitions=None)
        instance.specialization_source=source
        instance.specialization_kinds=key[1]
        if hasattr(source,'qualified_name'):instance.qualified_name=source.qualified_name
        self.instances[key]=instance
        self.model.plans.append(instance)
        return instance


def native_target(model,source,bound):
    """Resolve a previously analyzed native body after original argument bind."""
    registry=getattr(model,'specializations',None)
    return source if registry is None else registry.select(source,bound,create=False)
