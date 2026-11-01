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


def runtime_value(cell,node):
    from .native_classes import ClassUnsupported
    root=cell.root()
    if isinstance(root.tag,AnnotationAlias):
        raise ClassUnsupported(node,root.tag.module+'.'+root.tag.name+' is available as an imported annotation/compiler symbol; observing or calling this object at runtime needs its unimplemented metadata-object protocol',proof='runtime annotation/compiler symbol value protocol')
    if root.tag=='union':
        for child in root.args:runtime_value(child,node)


SIGNATURE=FunctionSignature.declaration(('typ','val'))


@dataclass(frozen=True)
class CastCall:
    result:object
    error:str|None=None


class TypingAdapter:
    NAMES=frozenset({'cast'})

    @staticmethod
    def analyze(model,plan,node,identity,normalized_call,positional,keywords,environment,*,factory):
        try:
            bound=SIGNATURE.bind(positional,keywords)
        except CallBindingError as error:
            from .native_aot_callables import binding_error
            selected=SimpleNamespace(signature=SIGNATURE,qualified_name='cast',node=node.func)
            return CastCall(factory('none'),binding_error(selected,normalized_call,error))
        return CastCall(bound['val'])

    @staticmethod
    def emit(emitter,node,identity,record,positional,keywords):
        from .native import _string
        from .native_classes import Expression,shape
        wanted=shape(record.result)
        if record.error is not None:
            return Expression(emitter.at('Err::<'+emitter.rust_type(wanted)+',String>('+_string(record.error)+'.to_owned())',node),wanted)
        value=SIGNATURE.bind(positional,keywords)['val']
        return Expression(emitter.coerce(value,wanted,node),wanted)
