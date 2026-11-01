"""Canonical builtin singleton values distinct from None and callable objects."""
import ast
from dataclasses import dataclass


@dataclass(frozen=True)
class BuiltinSingleton:
    name:str
    type_name:str
    _native_builtin_singleton=True
    _native_reference_cloneable=True
    _native_stored_reference=True

    @property
    def _native_kind_tag(self):return 'builtin_singleton_'+self.name


NOT_IMPLEMENTED=BuiltinSingleton('NotImplemented','NotImplementedType')
SINGLETONS={'NotImplemented':NOT_IMPLEMENTED}


def requires_frames(unit,analysis):
    recorded={site for facts in analysis.scopes.values()for site in set(facts.values)|set(facts.expressions)}
    writes={(binding.owner,binding.name)for binding in unit.bindings if binding.role not in {'load','parameter'}}
    unresolved={site for facts in analysis.scopes.values()for site,value in facts.values.items()if value.unbound or value.unknown}
    return any(binding.role=='load'and binding.node in recorded
        and binding.name in SINGLETONS and unit.scopes[binding.owner].kind=='module'
        and((binding.owner,binding.name)not in writes or binding.node in unresolved)for binding in unit.bindings)


def canonical_kind(model,plan,node,environment):
    if not isinstance(node,ast.Name)or node.id not in SINGLETONS:return None
    name=model.resolved_name(plan,node)
    binding=model.namespace.owners.get(model.unit.ordinal(node))
    if binding is None or not model.module_owner(binding.owner):return None
    if name in environment or name in model.classes or name in model.functions or name in model.global_symbols:return None
    from .native_classes import ClassUnsupported
    if name in model.global_written_names:
        raise ClassUnsupported(node,"this builtin singleton name also has a module-owned write; its lookup may need the original builtin fallback before that write, and a mutable singleton namespace adapter is not implemented",proof="canonical builtin singleton binding before and after writes")
    linker=getattr(model,'module_linker',None)
    if linker is not None and 'builtins'in linker.modules:
        key=model.unit.global_name('builtins',node.id)
        if key in model.namespace.incoming or key in model.namespace.active:
            raise ClassUnsupported(node,"the canonical builtins singleton namespace may be modified; runtime fallback lookup for that mutable singleton field is not implemented",proof="unmodified canonical builtin singleton namespace")
    return SINGLETONS[node.id]


def analyze(model,plan,node,environment):
    kind=canonical_kind(model,plan,node,environment)
    if kind is None:return None
    if not hasattr(model,'builtin_singleton_sites'):model.builtin_singleton_sites={}
    model.builtin_singleton_sites[(plan.index,id(node))]=kind
    model.builtin_singletons_used=True
    return model.cell(plan,node,kind)


def read(emitter,node):
    kind=getattr(emitter.model,'builtin_singleton_sites',{}).get((emitter.plan.index,id(node)))
    if kind is None:return None
    from .native_classes import Expression
    return Expression('NativeNotImplemented',kind)


def has_singleton(kind):
    from .native_types import alternatives
    return any(isinstance(part,BuiltinSingleton)for part in alternatives(kind))


def truth(emitter,value,node):
    from .native_classes import ClassUnsupported
    if node is None:
        raise ClassUnsupported(emitter.plan.node,"truth testing this builtin singleton needs its original source demand location; this implicit truth-consumer adapter does not yet forward that location",types=(("value",value.kind),),proof="fallible singleton truth demand")
    return emitter.at('Err::<bool,String>("TypeError: NotImplemented should not be used in a boolean context".to_owned())',node)


def runtime(model):
    if not getattr(model,'builtin_singletons_used',False):return ''
    return '#[derive(Clone,Copy,PartialEq,Eq)]\nstruct NativeNotImplemented;\n'
