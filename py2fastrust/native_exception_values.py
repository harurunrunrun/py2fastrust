"""Finite builtin exception identities, typed argument payloads, and explicit raise."""
import ast
from dataclasses import dataclass


PARENTS={'BaseException':None,'Exception':'BaseException','LookupError':'Exception',
         'IndexError':'LookupError','ValueError':'Exception','TypeError':'Exception',
         'RuntimeError':'Exception','StopIteration':'Exception'}
NAMES=frozenset(PARENTS)


def exception_subclass(name,parent):
    while name is not None:
        if name==parent:return True
        name=PARENTS.get(name)
    return False


@dataclass(frozen=True)
class ExceptionClass:
    name:str
    _native_exception_class=True
    _native_reference_cloneable=True
    _native_stored_reference=True
    _native_python_type_name='type'

    @property
    def _native_kind_tag(self):return 'exception_class_'+self.name


CLASSES={name:ExceptionClass(name)for name in NAMES}


@dataclass(frozen=True)
class ExceptionValue:
    record:object
    _native_exception_value=True
    _native_reference_cloneable=True
    _native_stored_reference=True

    @property
    def _native_kind_tag(self):return 'exception_value_'+str(self.record.index)

    @property
    def _native_python_type_name(self):return self.record.owner.name

    @property
    def _native_owned_kinds(self):
        from .native_classes import shape
        return tuple(shape(value)for value in self.record.arguments)


@dataclass(eq=False)
class Constructor:
    index:int
    owner:ExceptionClass
    arguments:tuple
    result:object
    node:object
    error:str|None=None
    potentially_stored:bool=False


def requires_frames(unit,analysis):
    recorded={site for facts in analysis.scopes.values()for site in set(facts.expressions)|set(facts.values)}
    nodes={unit.ordinal(node):node for node in ast.walk(unit.tree)}
    if any(site in recorded and isinstance(node,ast.Name)and node.id in NAMES for site,node in nodes.items()):return True
    return any(isinstance(node,ast.Raise)for node in nodes.values())


def is_stop(emitter,error):
    if emitter.model.exceptions.used:return 'class_exception_is_stop(&'+error+')'
    return error+'.message=="StopIteration"||'+error+'.message.starts_with("StopIteration:")'


def stop_iteration(emitter,node,wanted):
    if emitter.model.exceptions.used:
        visible=getattr(emitter,'exception_origin_visible',True)
        visible=str(visible).lower()if isinstance(visible,bool)else visible
        return 'class_exception_stop_iteration::<'+emitter.rust_type(wanted)+'>('+str(node.lineno)+','+emitter.location_code()+','+visible+')?'
    return emitter.at('Err::<'+emitter.rust_type(wanted)+',String>("StopIteration".to_owned())',node)


def closed_argument(kind):
    from .native_types import ListType,TupleType,TupleSequenceType,EmptyType,alternatives
    if kind is None:return True
    for part in alternatives(kind):
        if isinstance(part,EmptyType)or part in {'int','bool','int_bool','float','str','bytes','none'}:continue
        if isinstance(part,(ListType,TupleSequenceType))and closed_argument(part.element):continue
        if isinstance(part,TupleType)and all(closed_argument(field)for field in part.fields):continue
        return False
    return True


class Exceptions:
    def __init__(self,model):
        self.model=model;self.records=[];self.constructors={};self.names={};self.raises={}
        self.protocol_required=False
        self.identity_sites={}
        self.repr_records=set()
        model.generator_exception_protocol=self

    @property
    def used(self):return bool(self.names or self.records or self.raises or self.protocol_required)

    def require(self,node):
        self.protocol_required=True

    def observe_identity(self,plan,node):
        self.identity_sites[(plan.index,id(node))]=node

    def validate(self):
        from .native_classes import ClassUnsupported,shape
        from .native_types import alternatives,TupleType
        from .native_integer_digit_limits import validate_payload
        for record in self.records:
            validate_payload(self.model,TupleType(tuple(shape(value)for value in record.arguments)),
                             record.node,'An explicit exception argument tuple')
        retained=any(isinstance(kind,ExceptionValue)and kind.record.potentially_stored
                     for value,_ in self.raises.values()for kind in alternatives(shape(value)))
        if retained and self.identity_sites:
            node=next(iter(self.identity_sites.values()))
            raise ClassUnsupported(node,'id() together with a raised stored exception can observe local objects retained by Python traceback frames; native exceptions retain typed arguments and logical traceback locations, but complete native frame-root retention is not implemented',proof='object identity and retained exception frame roots')

    def name(self,plan,node,environment):
        from .native_classes import ClassUnsupported
        if not isinstance(node,ast.Name)or node.id not in NAMES:return None
        name=self.model.resolved_name(plan,node)
        binding=self.model.namespace.owners.get(self.model.unit.ordinal(node))
        if binding is None or not self.model.module_owner(binding.owner):return None
        if name in environment or name in self.model.classes or name in self.model.functions or name in self.model.global_symbols:return None
        if name in self.model.global_written_names:
            raise ClassUnsupported(node,'this builtin exception class also has a module-owned write; mutable builtin exception namespace fallback is not implemented',proof='canonical exception-class binding ownership')
        linker=getattr(self.model,'module_linker',None)
        if linker is not None and 'builtins'in linker.modules:
            key=self.model.unit.global_name('builtins',node.id)
            if key in self.model.namespace.incoming or key in self.model.namespace.active:
                raise ClassUnsupported(node,'this exception-class read may observe a modified builtins namespace; mutable exception-class fallback is not implemented',proof='unmodified canonical exception class')
        kind=CLASSES[node.id];self.names[(plan.index,id(node))]=kind
        return self.model.cell(plan,node,kind)

    def read(self,emitter,node):
        from .native_classes import Expression
        kind=self.names.get((emitter.plan.index,id(node)))
        return None if kind is None else Expression('ClassExceptionClass'+kind.name,kind)

    def construct(self,plan,node,owner,positional,keywords):
        from .native_classes import Cell,ClassUnsupported,shape
        key=plan.index,id(node),owner
        if key not in self.constructors:
            record=Constructor(len(self.records),owner,tuple(Cell()for _ in positional),Cell(),node)
            if not isinstance(node,ast.Raise):
                parent=self.model.generators.parents.get(id(node))
                record.potentially_stored=not(isinstance(parent,ast.Raise)and parent.exc is node)
            self.constructors[key]=record;self.records.append(record)
            self.model.contribute(record.result,Cell(ExceptionValue(record)),node)
        record=self.constructors[key]
        if len(record.arguments)!=len(positional):
            raise ClassUnsupported(node,'this exception constructor receives a runtime-varying argument count; a typed exception-argument sequence adapter is not implemented',proof='finite exception argument tuple layout')
        for slot,value in zip(record.arguments,positional):
            if not closed_argument(shape(value)):
                raise ClassUnsupported(node,'this exception argument requires custom repr/str or recursive exception-object ownership; the typed exception payload currently supports closed builtin values and finite builtin containers',types=(('argument',shape(value)),),proof='closed exception argument display and ownership')
            self.model.contribute(slot,value,node)
        record.error=owner.name+'() takes no keyword arguments'if keywords else None
        return record

    def emit_construct(self,emitter,node,record,positional,keywords,wanted):
        from .native_classes import Expression,shape
        from .native import _string
        if record.error:
            code=emitter.at('Err::<'+emitter.rust_type(wanted)+',String>('+_string('TypeError: '+record.error)+'.to_owned())',node)
            return Expression(code,wanted)
        fields=[emitter.coerce(value,shape(slot),node)for value,slot in zip(positional,record.arguments)]
        args='('+','.join(fields)+(','if len(fields)==1 else'')+')'
        code=f'Rc::new(ClassExceptionValue{record.index}{{payload:Rc::new(ClassExceptionPayload{record.index}{{args:{args}}}),trace:class_exception_state_new(&class_scope)}})'
        return emitter.encoded(code,ExceptionValue(record),wanted,node)

    def analyze_raise(self,plan,node,environment):
        from .native_classes import ClassUnsupported,shape
        from .native_types import alternatives
        if node.cause is not None:
            raise ClassUnsupported(node,'explicit exception causes require raise-from cause binding and suppression metadata; that source protocol is not implemented',proof='explicit exception cause protocol')
        if node.exc is None:
            raise ClassUnsupported(node,'bare raise requires the current active exception object, including cleanup frames; that active-exception namespace is not implemented',proof='active exception object for bare raise')
        value=self.model.expression(plan,node.exc,environment)
        records={}
        for kind in alternatives(shape(value)):
            if isinstance(kind,ExceptionClass):records[kind]=self.construct(plan,node,kind,[],[])
        self.raises[(plan.index,id(node))]=(value,records)

    def emit_raise(self,emitter,node):
        from .native_classes import Expression
        from .native_unions import project,union_kind
        value,records=self.raises[(emitter.plan.index,id(node))]
        before,current=emitter.capture(emitter.expression(node.exc))
        def branch(kind,code):
            setup=''
            if isinstance(kind,ExceptionClass):
                record=records[kind]
                constructed=self.emit_construct(emitter,node,record,[],[],ExceptionValue(record))
                setup,item=emitter.capture(constructed)
            elif isinstance(kind,ExceptionValue):item=Expression('('+code+').clone()',kind)
            else:
                return '{'+emitter.at('Err::<(),String>("TypeError: exceptions must derive from BaseException".to_owned())',node)+';}'
            error=emitter.fresh()
            return '{'+setup+f'let {error}=class_exception_raise({item.code}.payload.clone(),{item.code}.trace.clone(),{node.lineno},{emitter.location_code()});return Err({error});'+'}'
        return before+(project(current.kind,current.code,branch)if union_kind(current.kind)else branch(current.kind,current.code))+';'

    def payloads(self,emitter):
        from .native_classes import Expression,shape
        from .native_types import TupleType
        from .native import _string
        classes={kind.name for kind in self.names.values()}|{record.owner.name for record in self.records}
        result=['#[derive(Clone,Copy)]\nstruct ClassExceptionClass'+name+';'for name in sorted(classes)]
        for record in self.records:
            kinds=tuple(shape(value)for value in record.arguments)
            for kind in kinds:
                if kind is None or not closed_argument(kind):
                    from .native_classes import ClassUnsupported
                    raise ClassUnsupported(record.node,'exception constructor argument layout remains unresolved before emission',proof='complete typed exception argument tuple')
            kind=TupleType(kinds);rust=emitter.rust_type(kind)
            arguments=[Expression('self.args.'+str(i)+'.clone()',field)for i,field in enumerate(kinds)]
            text='String::new()'if not arguments else emitter.show(arguments[0],record.node)if len(arguments)==1 else emitter.show(Expression('self.args.clone()',kind),record.node)
            result.append(f'struct ClassExceptionPayload{record.index}{{args:{rust}}}')
            result.append(f'impl std::fmt::Debug for ClassExceptionPayload{record.index}{{fn fmt(&self,f:&mut std::fmt::Formatter<\'_>)->std::fmt::Result{{f.write_str('+_string(record.owner.name)+')}}')
            repr_method=''
            if record.index in self.repr_records:
                represented=[emitter.show(value,record.node,True)for value in arguments]
                repr_args='vec!['+','.join(represented)+'].join(", ")'if represented else'String::new()'
                repr_method='fn class_repr(&self)->String{format!("'+record.owner.name+'({})",'+repr_args+')}'
            result.append(f'impl ClassExceptionPayload for ClassExceptionPayload{record.index}{{fn class_kind(&self)->ClassExceptionKind{{ClassExceptionKind::'+record.owner.name+'}fn class_name(&self)->&\'static str{'+_string(record.owner.name)+'}fn class_str(&self)->String{'+text+'}'+repr_method+'}')
            result.append(f'struct ClassExceptionValue{record.index}{{payload:Rc<ClassExceptionPayload{record.index}>,trace:Rc<RefCell<Option<NativeError>>>}}')
        return '\n'.join(result)


def show(emitter,value,node,representation=False):
    from .native import _string
    if isinstance(value.kind,ExceptionClass):return _string("<class '"+value.kind.name+"'>")+'.to_owned()'
    if representation:emitter.model.exceptions.repr_records.add(value.kind.record.index)
    return value.code+'.payload.class_'+('repr'if representation else'str')+'()'


def comparison(operator,left,right):
    if not isinstance(operator,(ast.Is,ast.IsNot,ast.Eq,ast.NotEq)):return None
    values=(ExceptionClass,ExceptionValue)
    if not(isinstance(left.kind,values)or isinstance(right.kind,values)):return None
    same='false'
    if left.kind==right.kind:
        same='true'if isinstance(left.kind,ExceptionClass)else'Rc::ptr_eq(&'+left.code+',&'+right.code+')'
    return '!('+same+')'if isinstance(operator,(ast.IsNot,ast.NotEq))else same
