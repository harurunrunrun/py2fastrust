"""Canonical deferred-annotation imports and the value-preserving cast call."""
from dataclasses import dataclass
from types import SimpleNamespace

from .call_semantics import FunctionSignature,CallBindingError


ALIASES=frozenset({'Any','Tuple','List','Dict','Set','FrozenSet','Optional','Union',
                  'Callable','Sequence','Iterable','Iterator','Mapping',
                  'MutableMapping','MutableSequence','Collection','Type',
                  'ClassVar','Final','Literal','Annotated','NoReturn','Self','TypeAlias'})
FEATURES=frozenset({'nested_scopes','generators','division','absolute_import',
                   'with_statement','print_function','unicode_literals',
                   'generator_stop','annotations'})


@dataclass(frozen=True)
class AnnotationAlias:
    name:str
    module:str='typing'
    _native_stored_reference=True
    _native_reference_cloneable=True
    _native_owned_kinds=()

    @property
    def _native_kind_tag(self):return 'annotation_'+self.module+'_'+self.name


def seed_alias(linker,module,name):
    if not module.native_adapter:return False
    if not(module.name=='typing'and name in ALIASES or module.name=='__future__'and name in FEATURES):return False
    from .native_classes import Cell
    key=linker.unit.global_name(module.name,name)
    alias=AnnotationAlias(name,module.name)
    linker.model.namespace.incoming.setdefault(key,{})[('typing_annotation',name)]=Cell(alias)
    linker.model.namespace.active.add(key)
    linker.model.namespace.refresh(key,linker.model.tree)
    linker.annotation_aliases[key]=(module.number,alias)
    return True


def runtime_value(cell,node,model=None,plan=None):
    from .native_classes import shape
    from .native_typing_metadata import contains,registry,reject_observation
    if contains(shape(cell)):
        if model is not None and registry(model).allowed(plan,node,shape(cell)):return
        reject_observation(shape(cell),node)


SIGNATURE=FunctionSignature.declaration(('typ','val'))


@dataclass(frozen=True)
class CastCall:
    result:object
    error:str|None=None


class TypingAdapter:
    NAMES=frozenset({'cast','NamedTuple','TypeVar'})
    TYPES=frozenset({'TypeVar'})

    @staticmethod
    def match_type(emitter,node,value,name):
        from .native_unions import project,union_kind
        from .native_classes import Expression
        from .native_typing_metadata import MetadataType
        import typing
        if union_kind(value.kind):
            return project(value.kind,value.code,lambda kind,code:TypingAdapter.match_type(emitter,node,Expression(code,kind),name))
        if name!='TypeVar'or not isinstance(value.kind,MetadataType):return 'false'
        selected=[index for index,item in enumerate(value.kind.record.values)if isinstance(item,typing.TypeVar)]
        return '('+'||'.join(f'({value.code}).case=={index}'for index in selected)+')'if selected else'false'

    @staticmethod
    def analyze(model,plan,node,identity,normalized_call,positional,keywords,environment,*,factory):
        if identity.name=='TypeVar':
            from .native_typing_typevars import analyze
            return analyze(model,plan,node,normalized_call,positional,keywords,factory=factory)
        if identity.name=='NamedTuple':
            from .native_classes import ClassUnsupported
            raise ClassUnsupported(node,'functional typing.NamedTuple construction requires dynamic field/factory generation; only canonical class declarations are implemented',proof='runtime named tuple factory construction')
        try:
            bound=SIGNATURE.bind(positional,keywords)
        except CallBindingError as error:
            from .native_aot_callables import binding_error
            selected=SimpleNamespace(signature=SIGNATURE,qualified_name='cast',node=node.func)
            return CastCall(factory('none'),binding_error(selected,normalized_call,error))
        return CastCall(bound['val'])

    @staticmethod
    def emit(emitter,node,identity,record,positional,keywords):
        if identity.name=='TypeVar':
            from .native_typing_typevars import emit
            return emit(emitter,node,record,positional,keywords)
        from .native import _string
        from .native_classes import Expression,shape
        wanted=shape(record.result)
        if record.error is not None:
            return Expression(emitter.at('Err::<'+emitter.rust_type(wanted)+',String>('+_string(record.error)+'.to_owned())',node),wanted)
        value=SIGNATURE.bind(positional,keywords)['val']
        return Expression(emitter.coerce(value,wanted,node),wanted)
