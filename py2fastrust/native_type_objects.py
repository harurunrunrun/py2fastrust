"""Actual builtin class objects and retained source-instance class lookup."""
import ast,builtins
from dataclasses import dataclass

from .references import BuiltinIdentity


BUILTIN_CLASSES=frozenset(name for name,value in vars(builtins).items()if isinstance(value,type))
NEW_VALUES=frozenset({'type','complex','object','frozenset','bytearray','memoryview'})


@dataclass(frozen=True)
class BuiltinClass:
    name:str
    _native_builtin_type=True
    _native_reference_cloneable=True
    _native_stored_reference=True
    _native_python_type_name='type'
    @property
    def _native_kind_tag(self):return 'builtin_class_'+self.name
    @property
    def rust(self):return 'ClassBuiltinType_'+self.name


def class_kind(model,name):
    if not hasattr(model,'builtin_class_objects'):model.builtin_class_objects=set()
    model.builtin_class_objects.add(name)
    return BuiltinClass(name)


def builtin_value(model,identity):
    if isinstance(identity,BuiltinIdentity)and identity.name in NEW_VALUES:
        from .native_classes import Cell
        return Cell(class_kind(model,identity.name))
    return None


def requires_frames(unit,analysis):
    return any(BuiltinIdentity('type')in call.identity.alternatives
               for facts in analysis.scopes.values()for call in facts.calls.values())or any(
        BuiltinIdentity('type')in value.alternatives
        for facts in analysis.scopes.values()for value in facts.values.values())


def requires_linking(program):
    # A possible canonical type value in a class-containing unit needs the
    # existing class-definition holder. Selection makes no binding assumption.
    if not any(isinstance(node,ast.ClassDef)for unit in program.units for node in ast.walk(unit.tree)):return False
    return any(binding.name=='type'and binding.role=='load'
               and unit.scopes[binding.owner].kind=='module'
               for unit in program.units for binding in unit.bindings)


def binding_error(count,keywords):
    if count==1:return 'TypeError: type() takes no keyword arguments'if keywords else None
    if count!=3:return 'TypeError: type() takes 1 or 3 arguments'
    return None


def legacy_class(target):
    from .native_module_calls import BuiltinRef
    if isinstance(target,BuiltinIdentity)and target.name in BUILTIN_CLASSES:return BuiltinClass(target.name)
    if isinstance(target,BuiltinRef)and target.module=='builtins'and target.name in BUILTIN_CLASSES:return BuiltinClass(target.name)
    return None


def callable_metatype(model,target,node):
    from .native_bound_methods import BoundMethodTarget
    from .native_module_calls import BuiltinRef
    from .native_classes import ClassUnsupported
    if legacy_class(target)is not None:return 'type'
    if isinstance(target,int):return 'function'
    if isinstance(target,BoundMethodTarget):return 'method'
    if isinstance(target,BuiltinIdentity)and target.name not in {'exit','quit'}:return 'builtin_function_or_method'
    if isinstance(target,BuiltinRef):
        adapter=model.callable_cells.member_adapters.get(target.module)
        if adapter is not None:
            if target.name in getattr(adapter,'TYPES',()):return 'type'
            if hasattr(adapter,'member_type_name'):
                name=adapter.member_type_name(target.name)
                if name in {'type','function','method','builtin_function_or_method'}:return name
    raise ClassUnsupported(node,'the actual Python class of this native callable needs verified callable-class metadata; that metatype adapter is not implemented',types=(('native callable',target),),proof='native callable-class identity metadata')


def instance_classes(model,kind,node):
    from .native_classes import ClassUnsupported,InstanceType
    from .native_types import ListType,TupleType,TupleSequenceType,EmptyType
    from .native_module_linking import ClassReferenceType,ModuleType
    from .native_aot_callables import function_kind
    from .native_bound_methods import BoundMethodTarget
    if isinstance(kind,EmptyType):return (kind,)
    if kind is None:return ()
    if isinstance(kind,BuiltinClass)or isinstance(kind,ClassReferenceType)or getattr(kind,'_native_exception_class',False):return (class_kind(model,'type'),)
    if isinstance(kind,InstanceType):
        if not hasattr(model,'module_linker'):
            raise ClassUnsupported(node,'type() of this source instance needs its retained actual class-definition reference; that holder is unavailable on this nonlinked frame',types=(('value',kind),),proof='actual source class-definition identity')
        return (ClassReferenceType(model.classes[kind.name].index),)
    if getattr(kind,'_native_named_tuple',False):
        raise ClassUnsupported(node,'type() of this NamedTuple needs a retained per-value class-definition holder; the immutable tuple payload does not expose that class identity yet',types=(('value',kind),),proof='NamedTuple actual class-definition holder')
    if kind=='int_bool':return (class_kind(model,'int'),class_kind(model,'bool'))
    if getattr(kind,'_native_bytearray',False):return (class_kind(model,'bytearray'),)
    if getattr(getattr(kind,'record',None),'operation',None)in {'source_generator','retained_generator_expression'}:
        return (class_kind(model,'generator'),)
    if kind in {'int','bool','float','str','bytes','complex','range','none'}:return (class_kind(model,'NoneType'if kind=='none'else kind),)
    if isinstance(kind,ListType):return (class_kind(model,'list'),)
    if isinstance(kind,(TupleType,TupleSequenceType)):return (class_kind(model,'tuple'),)
    if getattr(kind,'_native_class_mapping',False)and kind.record.flavor in {'dict','set'}:return (class_kind(model,kind.record.category),)
    if getattr(kind,'_native_namespace_view',False):return (class_kind(model,'dict'),)
    if getattr(kind,'_native_builtin_singleton',False):return (class_kind(model,kind.type_name),)
    if isinstance(kind,ModuleType)or kind=='sys':return (class_kind(model,'module'),)
    if getattr(kind,'_native_bound_mapping_method',False):return (class_kind(model,'builtin_function_or_method'),)
    if function_kind(kind):
        result=[]
        for target in kind.targets:result.append(class_kind(model,callable_metatype(model,target,node)))
        return tuple(result)
    raise ClassUnsupported(node,'type() cannot expose the actual Python class object for this stored value; its native metatype/constructor carrier is not implemented',types=(('value',kind),),proof='actual class-object identity and metatype representation')


def analyze_type(model,plan,node,arguments,keywords,factory):
    from .native_classes import shape
    from .native_types import alternatives
    error=binding_error(len(arguments),keywords)
    if error:return factory('none')
    if len(arguments)==3:
        from .native_classes import ClassUnsupported
        raise ClassUnsupported(node,'three-argument type(name, bases, namespace) constructs a dynamic class; dynamic class construction and metaclass publication are not implemented',proof='dynamic type class construction')
    kind=shape(arguments[0]);result=factory()
    if kind is None:
        if not model.final:return result
        from .native_classes import ClassUnsupported
        raise ClassUnsupported(node,'type() operand has unresolved native storage after inference; its actual class object cannot be proved',proof='resolved operand storage for actual class lookup')
    for choice in alternatives(kind):
        for output in instance_classes(model,choice,node):model.contribute(result,model.cell_for_kind(output),node)
    return result


def emit_type(emitter,node,arguments,keywords,wanted):
    from .native_classes import Expression,InstanceType
    from .native_types import EmptyType
    from .native_unions import project
    from .native_aot_callables import function_kind
    from .native_callable_carriers import dispatch
    def branch(kind,code):
        if isinstance(kind,EmptyType):return 'native_empty::<'+emitter.rust_type(wanted)+'>('+code+')'
        if isinstance(kind,InstanceType):
            output=instance_classes(emitter.model,kind,node)[0]
            value='{let value=('+code+').borrow().class_definition.clone();value}'
            return emitter.coerce(Expression(value,output),wanted,node)
        if kind=='int_bool':
            a,b=class_kind(emitter.model,'int'),class_kind(emitter.model,'bool')
            return 'match '+code+'{NativeScalar::Int(_)=>'+emitter.coerce(Expression(a.rust,a),wanted,node)+',NativeScalar::Bool(_)=>'+emitter.coerce(Expression(b.rust,b),wanted,node)+'}'
        if function_kind(kind):
            def select(target,payload):
                from .native_aot_callables import AotFunctionType
                output=instance_classes(emitter.model,AotFunctionType.from_targets((target,)),node)[0]
                return emitter.coerce(Expression(output.rust,output),wanted,node)
            return dispatch(emitter,kind,code,select)
        output=instance_classes(emitter.model,kind,node)[0]
        return emitter.coerce(Expression(output.rust,output),wanted,node)
    return Expression(project(arguments[0].kind,arguments[0].code,branch),wanted)


@dataclass
class Constructor:
    result:object
    operation:object=None
    site:object=None
    error:str|None=None


def analyze_constructor(provider,plan,node,kind,metadata,positional,keywords,environment):
    from .native_classes import ClassUnsupported
    model=provider.model
    if kind.name=='NoneType':
        error='TypeError: NoneType takes no arguments'if positional or keywords else None
        return Constructor(model.cell(plan,node,'none',identity=('builtin_class_call',kind)),error=error)
    from .native_class_builtins import SUPPORTED
    if kind.name not in SUPPORTED:
        raise ClassUnsupported(node,'calling the returned '+kind.name+' class needs its actual constructor binding and allocation protocol; that constructor is not implemented',proof='returned builtin class constructor protocol')
    from .native_aot_callables import CallSite
    from .native_builtin_callables import analyze
    from .native_classes import Cell
    site=CallSite(Cell(kind),model.cell(plan,node,identity=('builtin_class_constructor',kind)))
    identity=BuiltinIdentity(kind.name)
    result=analyze(provider,plan,node,identity,metadata,positional,keywords,environment,site)
    if kind.name=='list'and not positional and not keywords:
        from .native_classes import Cell
        from .native_types import EMPTY
        model.contribute(result.root().args[0],Cell(EMPTY),node)
    return Constructor(result,identity,site.builtins[identity])


def emit_constructor(emitter,node,kind,record,positional,keywords,wanted):
    from .native_classes import Expression
    if record.error:
        from .native_class_builtins import _error
        from .native import _string
        return _error(emitter,node,wanted,_string(record.error)+'.to_owned()')
    if kind.name=='NoneType':return emitter.encoded('()','none',wanted,node)
    from .native_builtin_callables import emit
    result=emit(emitter,node,record.operation,record.site,positional,keywords)
    return Expression(emitter.coerce(result,wanted,node),wanted)


def comparison(emitter,operator,left,right,node):
    from .native_classes import Expression,ClassUnsupported
    from .native_unions import project,union_kind
    from .native_types import alternatives
    if not any(isinstance(part,BuiltinClass)for kind in (left.kind,right.kind)for part in alternatives(kind)):return None
    if union_kind(left.kind):return project(left.kind,left.code,lambda kind,code:emitter.comparison(operator,Expression(code,kind),right,node))
    if union_kind(right.kind):return project(right.kind,right.code,lambda kind,code:emitter.comparison(operator,left,Expression(code,kind),node))
    if not isinstance(operator,(ast.Eq,ast.NotEq,ast.Is,ast.IsNot)):
        raise ClassUnsupported(node,'builtin class-object ordering/containment needs its Python type-object operator protocol, which is not implemented',types=(('left',left.kind),('right',right.kind)),proof='builtin class-object operator observer')
    if isinstance(left.kind,BuiltinClass)and isinstance(right.kind,BuiltinClass):code=str(left.kind==right.kind).lower()
    else:
        from .native_aot_callables import function_kind
        from .native_callable_carriers import dispatch
        actual,other=(left,right)if isinstance(left.kind,BuiltinClass)else(right,left)
        code=(dispatch(emitter,other.kind,other.code,lambda target,payload:str(legacy_class(target)==actual.kind).lower(),borrow=True)
              if function_kind(other.kind)else'false')
    return '!('+code+')'if isinstance(operator,(ast.NotEq,ast.IsNot))else code


def show(kind):
    from .native import _string
    return _string("<class '"+kind.name+"'>")+'.to_owned()'


def runtime(model):
    return '\n'.join('#[derive(Clone,Copy,PartialEq,Eq)]\nstruct '+BuiltinClass(name).rust+';'for name in sorted(getattr(model,'builtin_class_objects',())))


def canonical_matches(kind,identity):
    return (isinstance(kind,BuiltinClass)and identity.name in NEW_VALUES and kind.name==identity.name
            or getattr(kind,'_native_function_reference',False)and kind.targets==(identity,))


def analyze_attribute(model,plan,node,receiver):
    from .native_classes import ClassUnsupported,shape
    from .native_types import alternatives
    choices=alternatives(shape(receiver))
    if not choices or not all(isinstance(kind,BuiltinClass)for kind in choices):return None
    if node.attr not in {'__name__','__qualname__','__module__'}:
        raise ClassUnsupported(node,'builtin class attribute '+repr(node.attr)+' needs its Python type-descriptor lookup protocol, which is not implemented',types=(('class',shape(receiver)),),proof='builtin class metadata attribute protocol')
    if not hasattr(model,'builtin_type_attributes'):model.builtin_type_attributes=set()
    model.builtin_type_attributes.add((plan.index,id(node)))
    return model.cell(plan,node,'str')


def emit_attribute(emitter,node):
    if (emitter.plan.index,id(node))not in getattr(emitter.model,'builtin_type_attributes',()):return None
    from .native_classes import Expression
    from .native_unions import project
    from .native import _string
    before,owner=emitter.capture(emitter.expression(node.value))
    code=project(owner.kind,owner.code,lambda kind,code:'NativeText::from('+_string('builtins'if node.attr=='__module__'else kind.name)+')')
    return Expression('{'+before+code+'}','str')


def isinstance_match(emitter,value,classes,node):
    from .native_classes import Expression,domain
    from .native_unions import project,union_kind
    from .native_module_linking import ClassReferenceType,ModuleType
    from .native_aot_callables import function_kind
    from .native_callable_carriers import dispatch
    from .native_bound_methods import BoundMethodTarget
    if union_kind(value.kind):return project(value.kind,value.code,lambda kind,code:isinstance_match(emitter,Expression(code,kind),classes,node))
    name=classes.name;tag=domain(value.kind)
    if name=='object':return 'true'
    if name=='int':return str(tag in {'int','bool','int_bool'}).lower()
    if name=='bool'and tag=='int_bool':return 'matches!(&('+value.code+'),NativeScalar::Bool(_))'
    if name=='tuple':return str(tag in {'tuple','tuple_sequence'}).lower()
    if name=='NoneType':return str(tag=='none').lower()
    if name=='module':return str(isinstance(value.kind,ModuleType)or value.kind=='sys').lower()
    if getattr(value.kind,'_native_builtin_singleton',False):return str(value.kind.type_name==name).lower()
    if name=='type':
        if isinstance(value.kind,(BuiltinClass,ClassReferenceType))or getattr(value.kind,'_native_exception_class',False):return 'true'
        if function_kind(value.kind):return dispatch(emitter,value.kind,value.code,lambda target,payload:str(callable_metatype(emitter.model,target,node)=='type').lower(),borrow=True)
        return 'false'
    if name in {'function','method','builtin_function_or_method'}:
        if getattr(value.kind,'_native_bound_mapping_method',False):return str(name=='builtin_function_or_method').lower()
        if not function_kind(value.kind):return 'false'
        return dispatch(emitter,value.kind,value.code,lambda target,payload:str(callable_metatype(emitter.model,target,node)==name).lower(),borrow=True)
    return str(tag==name).lower()
