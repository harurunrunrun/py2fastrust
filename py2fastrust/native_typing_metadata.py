"""Closed typing metadata construction, with explicit unobserved consumers.

The carrier represents a compiler-known metadata value, never Python None.
Only pure builtin/source type symbols and closed immutable parameters enter
the official typing constructors. Source expressions still execute in order.
General metadata observation remains outside this native protocol.
"""
import ast
import builtins
import itertools
import typing
import warnings
from contextlib import contextmanager
from dataclasses import dataclass,field


@dataclass(frozen=True)
class MetadataType:
    index:int
    record:object=field(compare=False,hash=False,repr=False)
    _native_stored_reference=True
    _native_reference_cloneable=True
    _native_owned_kinds=()
    _native_typing_metadata=True
    @property
    def _native_kind_tag(self):return 'typing_metadata_'+str(self.index)


@dataclass
class Construction:
    index:int
    node:object
    values:list=field(default_factory=list)
    keys:list=field(default_factory=list)
    owner:object=None
    parameter:object=None
    errors:dict=field(default_factory=dict)
    def __post_init__(self):self.kind=MetadataType(self.index,self)
    def add(self,value):
        key=semantic_key(value)
        if key not in self.keys:self.keys.append(key);self.values.append(value)
        return self.keys.index(key)


def semantic_key(value):
    # Equal spellings do not make two separately constructed type variables
    # equal. TypeVar construction sites retain their actual stable host value.
    if isinstance(value,typing.TypeVar):return ('typevar_identity',id(value))
    if isinstance(value,tuple):return ('tuple',tuple(map(semantic_key,value)))
    if isinstance(value,list):return ('list',tuple(map(semantic_key,value)))
    if isinstance(value,type)and '_pytors_type_id'in vars(value):return ('source_type',vars(value)['_pytors_type_id'])
    origin=typing.get_origin(value)
    if origin is not None:return ('alias',type(value).__module__,type(value).__qualname__,semantic_key(origin),tuple(map(semantic_key,typing.get_args(value))))
    return (type(value).__module__,type(value).__qualname__,repr(value))


def metadata_kind(kind):
    from .native_typing_aliases import AnnotationAlias
    return isinstance(kind,AnnotationAlias)or isinstance(kind,MetadataType)


def contains(kind):
    from .native_types import alternatives,TupleType,ListType,TupleSequenceType
    if metadata_kind(kind):return True
    if isinstance(kind,TupleType):return any(map(contains,kind.fields))
    if isinstance(kind,(ListType,TupleSequenceType)):return contains(kind.element)
    values=alternatives(kind)
    return len(values)>1 and any(map(contains,values))


def registry(model):
    value=getattr(model,'typing_metadata',None)
    if value is None:value=Registry(model);model.typing_metadata=value
    return value


def snapshot(model):
    value=getattr(model,'typing_metadata',None)
    return ()if value is None else tuple((record.index,tuple(record.keys),tuple(sorted(record.errors.items())))for record in value.records)


class Registry:
    BUILTIN_TYPES=frozenset({'int','bool','float','str','bytes','list','tuple','dict','set','frozenset','range','type','object'})
    GENERIC_TYPES=frozenset({'list','tuple','dict','set','frozenset','type'})
    def __init__(self,model):
        self.model=model;self.records=[];self.sites={};self.permitted=set();self.source_types={}

    def fail(self,node,detail):
        from .native_classes import ClassUnsupported
        raise ClassUnsupported(node,'typing metadata '+detail,proof='closed unobserved metadata constructor protocol')

    @contextmanager
    def allow(self,plan,nodes):
        keys={(plan.index,id(node))for node in nodes}
        previous=self.permitted.copy();self.permitted.update(keys)
        try:yield
        finally:self.permitted=previous

    def allowed(self,plan,node,kind=None):
        if(plan.index,id(node))in self.permitted:return True
        parent=self.model.unit.parents.get(id(node))
        if isinstance(parent,(ast.Assign,ast.AnnAssign,ast.NamedExpr,ast.Return))and parent.value is node:return True
        if isinstance(parent,(ast.Tuple,ast.List))and node in parent.elts:return self.allowed(plan,parent)
        if isinstance(parent,ast.Subscript)and parent.value is node and self.allowed(plan,parent):
            from .native_types import TupleType,ListType,alternatives
            if kind is not None and all(isinstance(part,(TupleType,ListType))for part in alternatives(kind)):return True
        return False

    @contextmanager
    def arguments(self,plan,callee,arguments):
        from .native_classes import shape
        from .native_aot_callables import AotFunctionType
        from .native_types import alternatives
        from .native_module_calls import BuiltinRef
        from .native_typing_aliases import SIGNATURE
        from .call_semantics import CallBindingError
        kinds=alternatives(shape(callee));nodes=[]
        # Source functions transport values through their real typed formals;
        # each reached body separately proves every observed metadata read.
        source_only=lambda kind:isinstance(kind,AotFunctionType) and bool(kind.definitions) and not(kind.builtins or kind.members or kind.methods)
        compatible=lambda kind:isinstance(kind,AotFunctionType) and not(kind.builtins or kind.methods) and all(member==BuiltinRef('typing','cast')for member in kind.members)
        typevar=lambda kind:isinstance(kind,AotFunctionType) and not(kind.definitions or kind.builtins or kind.methods) and kind.members and all(member==BuiltinRef('typing','TypeVar')for member in kind.members)
        if all(source_only(kind)for kind in kinds):
            nodes=[arg.expression for arg in arguments.evaluation_order]
        elif kinds and all(typevar(kind)for kind in kinds):
            nodes=[arg.expression for arg in arguments.evaluation_order]
        elif all(compatible(kind)for kind in kinds)and any(kind.members for kind in kinds):
            try:
                bound=SIGNATURE.bind([arg.expression for arg in arguments.positional],[(arg.name,arg.expression)for arg in arguments.keywords])
                nodes=[bound['typ']]
            except CallBindingError:
                # Invalid binding occurs only after every argument expression.
                nodes=[arg.expression for arg in arguments.evaluation_order]
        elif not self.model.final and any(kind is None for kind in kinds):
            nodes=[arg.expression for arg in arguments.evaluation_order]
        with self.allow(plan,nodes):yield

    def source_type(self,kind,node):
        owner=self.model.class_namespaces.owners[kind.definition]
        # Class objects' hash/equality must be the builtin metaclass protocol.
        # Instance __eq__/__hash__ are irrelevant to class-object hashing.
        if owner.node.keywords:self.fail(node,'source class type arguments with metaclass keywords require their runtime metadata hash/equality protocol')
        if kind.definition not in self.source_types:
            name=self.model.class_namespaces.qualname(owner)
            self.source_types[kind.definition]=type(owner.node.name,(),{'__module__':owner.module_name,'__qualname__':name,'_pytors_type_id':kind.definition})
        return self.source_types[kind.definition]

    def choices(self,kind,node,plan):
        """Finite semantic values and predicates over captured native operands."""
        from .native_typing_aliases import AnnotationAlias
        from .native_classes import shape
        from .native_module_linking import ClassReferenceType
        from .native_aot_callables import AotFunctionType
        from .native_types import TupleType,ListType
        from .native_unions import union_kind,project
        if kind is None:return []
        if union_kind(kind):
            from .native_types import alternatives
            result=[]
            for part in alternatives(kind):
                for value,test in self.choices(part,node,plan):
                    result.append((value,lambda code,part=part,test=test:project(kind,code,lambda child,inner:test(inner)if child==part else'false')))
            return result
        if isinstance(kind,AnnotationAlias):
            if kind.module!='typing':self.fail(node,'future-feature objects require their own metadata protocol')
            return [(getattr(typing,kind.name),lambda code:'true')]
        if isinstance(kind,MetadataType):return [(value,lambda code,index=index:f'({code}).case=={index}')for index,value in enumerate(kind.record.values)]
        if isinstance(kind,ClassReferenceType):return [(self.source_type(kind,node),lambda code:'true')]
        if isinstance(kind,AotFunctionType):
            if kind.definitions or kind.methods or kind.members or any(identity.name not in self.BUILTIN_TYPES for identity in kind.builtins):
                if not self.model.final:return []
                self.fail(node,'type parameters containing arbitrary callables need their metadata hash/equality protocol')
            from .native_callable_carriers import test_target
            return [(getattr(builtins,identity.name),lambda code,target=identity:test_target(kind,code,target))for identity in kind.builtins]
        if isinstance(kind,TupleType):
            nodes=node.elts if isinstance(node,ast.Tuple)else[None]*len(kind.fields)
            members=[self.choices(part,child,plan)for part,child in zip(kind.fields,nodes)]
            return [(tuple(item[0]for item in selected),lambda code,selected=selected:'&&'.join('('+test(f'({code}).{index}')+')'for index,(_,test)in enumerate(selected))or'true')for selected in itertools.product(*members)]
        if isinstance(kind,ListType)and isinstance(node,ast.List):
            # Only original closed, pure type-symbol list literals are metadata
            # packs. Arbitrary mutable parameter lists need live-value metadata.
            if not all(isinstance(child,(ast.Name,ast.Attribute,ast.Constant))for child in node.elts):
                self.fail(node,'mutable/dynamic list parameter packs need their runtime metadata value protocol')
            members=[self.choices(shape(self.model.records[(plan.index,id(child))]),child,plan)for child in node.elts]
            return [(list(item[0]for item in selected),lambda code,selected=selected:'&&'.join('('+test(f'({code}).borrow()[{index}]')+')'for index,(_,test)in enumerate(selected))or'true')for selected in itertools.product(*members)]
        if kind=='none':return [(None,lambda code:'true')]
        if isinstance(node,ast.Constant)and type(node.value)in {int,bool,float,str,bytes}:
            value=node.value
            if type(value)is int:
                from .literal_semantics import integer_policy
                value=integer_policy(0 if self.model.integer=='bigint'else int(self.model.integer[1:])).normalize(value)
            return [(value,lambda code:'true')]
        if not self.model.final:return []
        self.fail(node,'parameters with dynamic scalar values or mutable packs need their runtime metadata value/validation protocol')

    def candidate(self,kind):
        from .native_types import alternatives
        from .native_aot_callables import AotFunctionType
        return any(metadata_kind(part)or isinstance(part,AotFunctionType)and any(identity.name in self.GENERIC_TYPES for identity in part.builtins)for part in alternatives(kind))

    def analyze(self,plan,node,environment):
        from .native_classes import Cell,shape
        if isinstance(node,ast.Constant)and node.value is Ellipsis and self.allowed(plan,node):
            key=plan.index,id(node)
            record=self.sites.get(key)
            if record is None:record=Construction(len(self.records),node);self.records.append(record);self.sites[key]=record
            record.add(Ellipsis)
            return self.model.remember(plan,node,Cell(record.kind))
        if not isinstance(node,ast.Subscript)or isinstance(node.slice,ast.Slice):return None
        owner=self.model.module_linker.pure_cell(plan,node.value,environment)
        candidate=owner is not None and self.candidate(shape(owner))
        if not candidate:
            from .references import BuiltinIdentity
            identity=self.model.builtin_identity(plan,node.value,environment)if isinstance(node.value,ast.Name)else None
            candidate=isinstance(identity,BuiltinIdentity)and identity.name in self.GENERIC_TYPES
        if not candidate and isinstance(node.value,ast.Subscript):
            with self.allow(plan,(node.value,)):
                owner=self.analyze(plan,node.value,environment)
            candidate=owner is not None and self.candidate(shape(owner))
        if not candidate:return None
        key=plan.index,id(node)
        record=self.sites.get(key)
        if record is None:record=Construction(len(self.records),node);self.records.append(record);self.sites[key]=record
        with self.allow(plan,(node.value,node.slice)):
            record.owner=self.model.expression(plan,node.value,environment)
            record.parameter=self.model.expression(plan,node.slice,environment)
        owners=self.choices(shape(record.owner),node.value,plan)
        parameters=self.choices(shape(record.parameter),node.slice,plan)
        for (receiver,_),(parameter,_)in itertools.product(owners,parameters):
            key=semantic_key(receiver),semantic_key(parameter)
            try:
                with warnings.catch_warnings(record=True)as emitted:
                    warnings.simplefilter('always')
                    value=receiver[parameter]
                if emitted:self.fail(node,'subscription emits warnings requiring their runtime warning/filter protocol')
            except (TypeError,SyntaxError,ValueError)as error:
                record.errors[key]=type(error).__name__+': '+str(error)
            else:record.add(value)
        return self.model.remember(plan,node,Cell(record.kind))

    def emit(self,emitter,node):
        from .native_classes import Expression,shape
        from .native import _string
        record=self.sites.get((emitter.plan.index,id(node)))
        if record is None:return None
        if isinstance(node,ast.Constant):return Expression('NativeTypingSymbol{case:0}',record.kind)
        setup,owner=emitter.capture(emitter.expression(node.value))
        before,parameter=emitter.capture(emitter.expression(node.slice));setup+=before
        owners=self.choices(owner.kind,node.value,emitter.plan);parameters=self.choices(parameter.kind,node.slice,emitter.plan)
        branches=[]
        for (receiver,owner_test),(argument,argument_test)in itertools.product(owners,parameters):
            key=semantic_key(receiver),semantic_key(argument)
            if key in record.errors:
                code=emitter.at('Err::<NativeTypingSymbol,String>('+_string(record.errors[key])+'.to_owned())',node)
            else:
                with warnings.catch_warnings():
                    warnings.simplefilter('error')
                    value=receiver[argument]
                code='NativeTypingSymbol{case:'+str(record.keys.index(semantic_key(value)))+'}'
            branches.append('if ('+owner_test(owner.code)+')&&('+argument_test(parameter.code)+'){'+code+'}else ')
        if not branches:self.fail(node,'constructor operands have no solved finite semantic cases')
        code=''.join(branches)+'{unreachable!("closed typing metadata operand")}'
        return Expression('{'+setup+code+'}',record.kind)


def reject_observation(kind,node):
    if contains(kind):
        from .native_classes import ClassUnsupported
        raise ClassUnsupported(node,'typing metadata-object protocol for runtime observation is not implemented; compiler-known type symbols are supported only by unobserved metadata constructors, typed value transport and the canonical typing.cast typ parameter',proof='runtime metadata observation')
