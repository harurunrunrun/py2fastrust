"""Canonical NamedTuple class factories over statically typed tuple payloads."""
import ast
from dataclasses import dataclass,field
from types import SimpleNamespace

from .call_semantics import FunctionSignature,normalize_call,CallBindingError
from .native_module_calls import BuiltinRef
from .native_types import NamedTupleType,TupleType

IDENTITY=BuiltinRef('typing','NamedTuple')


@dataclass(frozen=True)
class RecordTag:
    record: object
    _native_tuple_record=True

    def kind(self,fields):return NamedTupleType(tuple(fields),self.record)

    def __repr__(self):return 'record['+self.record.owner.node.name+']'


@dataclass(eq=False)
class Record:
    owner: object
    names: tuple
    annotations: tuple
    cells: tuple
    default_names: tuple
    signature: object
    reference_key: object
    validated: bool=False
    ready: bool=False

    @property
    def tag(self):return RecordTag(self)

    def kind(self):
        from .native_classes import shape
        return self.tag.kind(tuple(shape(value)for value in self.cells))


@dataclass
class RecordCall:
    record: Record
    result: object
    error: str|None=None


class NamedTuples:
    def __init__(self,namespaces):
        self.namespaces=namespaces
        self.model=namespaces.model
        self.records={}
        self.calls={}
        self.attributes={}

    def plan(self,owner):
        from .native_classes import Cell,ClassUnsupported
        node=owner.node
        if len(node.bases)!=1 or isinstance(node.bases[0],ast.Starred):
            raise ClassUnsupported(node,'class bases require inheritance/metaclass construction; no native factory is registered for this base layout',proof='canonical class factory base identity')
        names=[];annotations=[];present=set()
        for statement in node.body:
            if isinstance(statement,ast.AnnAssign)and isinstance(statement.target,ast.Name):
                name=statement.target.id
                if name.startswith('_')or name in names:
                    raise ClassUnsupported(statement,'NamedTuple field declarations need unique non-underscore names; this declaration is not supported',proof='NamedTuple declared field layout')
                names.append(name);annotations.append(statement.annotation)
            if isinstance(statement,ast.FunctionDef):
                raise ClassUnsupported(statement,'methods defined on a NamedTuple subclass require tuple-receiver method binding and special-method override validation; those adapters are not implemented',proof='NamedTuple source method binding')
        for statement in node.body:
            targets=statement.targets if isinstance(statement,ast.Assign)else(statement.target,)if isinstance(statement,(ast.AnnAssign,ast.AugAssign))and getattr(statement,'value',None)is not None else()
            for target in targets:
                for child in ast.walk(target):
                    if isinstance(child,ast.Name)and isinstance(child.ctx,ast.Store)and child.id in names:present.add(child.id)
            if isinstance(statement,ast.Delete):
                for target in statement.targets:
                    for child in ast.walk(target):
                        if isinstance(child,ast.Name)and isinstance(child.ctx,ast.Del):present.discard(child.id)
        defaults=tuple(name for name in names if name in present)
        if defaults and tuple(names[-len(defaults):])!=defaults:
            raise ClassUnsupported(node,'non-default NamedTuple fields after defaulted fields need the class factory validation error; this invalid default layout is not lowered',proof='NamedTuple trailing defaults')
        signature=FunctionSignature.declaration(('_cls',*names),default_names=defaults)
        record=Record(owner,tuple(names),tuple(annotations),tuple(Cell()for _ in names),defaults,signature,self.namespaces.key(owner,'\0record_definition'))
        self.records[owner.index]=record
        from .native_module_linking import ClassReferenceType
        namespace=self.model.namespace
        namespace.incoming.setdefault(record.reference_key,{})[('record_definition',self.model.unit.ordinal(node))]=Cell(ClassReferenceType(owner.index))
        namespace.active.add(record.reference_key);namespace.refresh(record.reference_key,node)
        fields=self.namespaces.member(owner,'_fields')
        self.namespaces.contribute(fields,Cell('tuple',tuple(Cell('str')for _ in names)),node,'record_fields')
        return record

    def prepare_definition(self,plan,node,environment):
        from .native_classes import ClassUnsupported,shape
        owner=self.model.classes[self.model.definition_name(node)]
        record=self.records.get(owner.index)
        if record is None:return
        value=self.model.expression(plan,node.bases[0],environment)
        kind=shape(value)
        if kind is None and not self.model.final:
            from .native_guard_flow import AnalysisPending
            raise AnalysisPending()
        if not getattr(kind,'_native_function_reference',False)or kind.targets!=(IDENTITY,):
            raise ClassUnsupported(node.bases[0],'this class base is not proved to be canonical typing.NamedTuple; inheritance and arbitrary metaclass factory construction are not implemented',types=(('base',kind),),proof='captured canonical NamedTuple factory identity')
        record.validated=True

    def finish_body(self,plan,environment):
        from .native_classes import ClassUnsupported,shape
        from .native_typing_aliases import AnnotationAlias
        from .native_module_linking import ClassReferenceType
        record=self.records.get(plan.class_body.index)if plan.class_body is not None else None
        if record is None:return
        for annotation in record.annotations:
            if isinstance(annotation,ast.Constant):
                if isinstance(annotation.value,str):
                    try:ast.parse(annotation.value,mode='eval')
                    except SyntaxError:
                        raise ClassUnsupported(annotation,'NamedTuple forward annotation text requires its runtime syntax-validation error; that metadata error adapter is not implemented',proof='NamedTuple forward annotation validation')from None
                continue
            if not isinstance(annotation,ast.Name):
                raise ClassUnsupported(annotation,'this NamedTuple field annotation needs expression evaluation and type validation after the class body; calls, subscriptions and attribute metadata are not implemented here',proof='ordered NamedTuple annotation evaluation')
            value=self.model.module_linker.pure_cell(plan,annotation,environment)
            kind=shape(value)if value is not None else None
            allowed=(kind is None or kind in {'int','bool','int_bool','float','none'}or
                     isinstance(kind,ClassReferenceType)or getattr(kind,'_native_function_reference',False)or
                     isinstance(kind,NamedTupleType)or isinstance(kind,AnnotationAlias)and kind.name in {'Any','NoReturn','Self','TypeAlias'})
            if not allowed:
                raise ClassUnsupported(annotation,'this NamedTuple annotation value needs its runtime typing metadata validation; the native factory does not erase that potentially failing protocol',types=(('annotation',kind),),proof='NamedTuple annotation validation without skipped effects')
        if not record.validated:return
        record.ready=True

    def snapshot(self):
        from .native_classes import shape
        return tuple((index,record.validated,record.ready,tuple(shape(value)for value in record.cells))for index,record in sorted(self.records.items()))

    def analyze_call(self,plan,node,owner,arguments,keywords,environment):
        from .native_classes import Cell
        record=self.records.get(owner.index)
        if record is None:return None
        if not record.ready:
            from .native_guard_flow import AnalysisPending
            if not self.model.final:raise AnalysisPending()
            from .native_classes import ClassUnsupported
            raise ClassUnsupported(node,'NamedTuple construction has no completed canonical class body/default/annotation proof',proof='initialized NamedTuple factory')
        defaults={name:self.namespaces.field(self.namespaces.member(owner,name),node)for name in record.default_names}
        from .native_module_linking import ClassReferenceType
        try:bound=record.signature.bind([Cell(ClassReferenceType(owner.index))]+arguments,keywords,defaults).by_name
        except CallBindingError as error:
            from .native_aot_callables import binding_error
            target=SimpleNamespace(signature=record.signature,node=owner.node,qualified_name=owner.node.name+'.__new__')
            result=self.model.cell(plan,node,'none')
            self.calls[(plan.index,id(node))]=RecordCall(record,result,binding_error(target,normalize_call(node),error,implicit_count=1))
            return result
        for name,destination in zip(record.names,record.cells):self.model.contribute(destination,bound[name],node)
        result=self.model.cell(plan,node,record.tag,record.cells)
        self.calls[(plan.index,id(node))]=RecordCall(record,result)
        return result

    def emit_call(self,emitter,node):
        from .native_classes import Expression,shape
        from .native import _string
        from .native_types import tuple_code
        site=self.calls.get((emitter.plan.index,id(node)))
        if site is None:return None
        record=site.record
        before,reference=emitter.capture(emitter.expression(node.func));lines=[before]
        positional=[];keywords=[]
        normalized=normalize_call(node)
        for argument in normalized.evaluation_order:
            before,value=emitter.capture(emitter.expression(argument.expression));lines.append(before)
            if argument.name is None:positional.append(value)
            else:keywords.append((argument.name,value))
        if site.error is not None:
            code=emitter.at(f'Err::<(),String>({_string(site.error)}.to_owned())',node)
            return Expression('{'+''.join(lines)+code+'}','none')
        defaults={}
        for name in record.default_names:
            member=self.namespaces.member(record.owner,name)
            index=self.model.namespace.index(member.key);stored=dict(self.model.namespace.fields())[member.key]
            code=emitter.at(f'{{let value={reference.code}.module.borrow().value_{index}.clone();value.ok_or_else(||"RuntimeError: NamedTuple default is not initialized".to_owned())}}',node)
            defaults[name]=Expression(code,stored)
        bound=record.signature.bind([reference]+positional,keywords,defaults).by_name
        kind=record.kind()
        code=tuple_code(emitter.coerce(bound[name],field,node)for name,field in zip(record.names,kind.fields))
        return emitter.encoded('{'+''.join(lines)+code+'}',kind,emitter.kind(node),node)

    def analyze_attribute(self,plan,node,receiver,environment):
        from .native_classes import Cell,shape,ClassUnsupported
        kind=shape(receiver)
        if not isinstance(kind,NamedTupleType):return None
        record=kind.record
        if node.attr in record.names:
            index=record.names.index(node.attr)
            self.attributes[(plan.index,id(node))]=('field',record,index)
            return self.model.remember(plan,node,receiver.root().args[index])
        if node.attr=='_fields':
            self.attributes[(plan.index,id(node))]=('fields',record,None)
            return self.model.cell(plan,node,'tuple',tuple(Cell('str')for _ in record.names))
        raise ClassUnsupported(node,f'NamedTuple member {node.attr!r} needs its inherited tuple method or class metadata descriptor adapter; that member is not implemented',types=(('receiver',kind),),proof='NamedTuple tuple/member protocol')

    def emit_attribute(self,emitter,node):
        from .native_classes import Expression
        from .native import _string
        from .native_types import tuple_code
        site=self.attributes.get((emitter.plan.index,id(node)))
        if site is None:return None
        operation,record,index=site
        before,value=emitter.capture(emitter.expression(node.value))
        if operation=='field':code=f'{value.code}.{index}.clone()'
        else:code=tuple_code(f'NativeText::from({_string(name)})'for name in record.names)
        return Expression('{'+before+code+'}',emitter.kind(node))

    def emit_prepare_definition(self,emitter,node):
        owner=self.model.classes[self.model.definition_name(node)]
        if owner.index not in self.records:return ''
        return ''.join('let _='+emitter.expression(base).code+';'for base in node.bases)

    def emit_retain_definition(self,emitter,node,owner,value):
        from .native_classes import Expression
        from .native_module_linking import ClassReferenceType
        record=self.records.get(owner.index)
        if record is None:return ''
        index=self.model.namespace.index(record.reference_key)
        from .native_types import tuple_code
        from .native import _string
        fields=self.namespaces.member(owner,'_fields')
        metadata=Expression(tuple_code('NativeText::from('+_string(name)+')'for name in record.names),TupleType(tuple('str'for _ in record.names)))
        return f'class_scope.globals.borrow_mut().value_{index}=Some(({value}).clone());'+self.namespaces.emit_store(emitter,fields,metadata,node)

    def class_member_guard(self,owner,name,node,*,writing=False):
        from .native_classes import ClassUnsupported
        record=self.records.get(owner.index)
        if record is None:return
        if name in record.names or writing and name in {'_fields','_field_defaults','_make','_replace','_asdict'}:
            raise ClassUnsupported(node,f'NamedTuple class member {name!r} needs its field/metadata descriptor object or mutation protocol; that adapter is not implemented',proof='NamedTuple field/metadata descriptor identity')

    def local_store_guard(self,owner,name,node):
        from .native_classes import ClassUnsupported
        if owner.index in self.records and name in {'_fields','_field_defaults','_make','_replace','_asdict'}:
            raise ClassUnsupported(node,f'NamedTuple factory metadata {name!r} cannot be replaced by an ordinary class-body data store',proof='NamedTuple protected factory metadata')


def show(emitter,value,node):
    from .native import _string
    from .native_classes import Expression
    record=value.kind.record
    if not record.names:return _string(record.owner.node.name+'()')+'.to_owned()'
    parts=[f'{_string(name+"=")}.to_owned()+&('+emitter.show(Expression(f'{value.code}.{index}.clone()',kind),node,True)+')'for index,(name,kind)in enumerate(zip(record.names,value.kind.fields))]
    return f'format!("{{}}({{}})",{_string(record.owner.node.name)},['+','.join(parts)+'].join(", "))'
