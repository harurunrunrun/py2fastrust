"""Owned canonical property descriptors and original source callback sites."""
import ast
from dataclasses import dataclass

from .native_types import EMPTY,EmptyType,alternatives


@dataclass(frozen=True)
class PropertyType:
    record:object
    _native_property=True
    _native_stored_reference=True
    _native_reference_cloneable=True
    _native_python_type_name='property'

    @property
    def _native_kind_tag(self):return 'property_'+str(self.record.index)

    @property
    def _native_owned_kinds(self):
        from .native_classes import shape
        return tuple(shape(value)for value in self.record.fields if shape(value)is not None)

    def __repr__(self):return 'PropertyType('+str(self.record.index)+')'


@dataclass(eq=False)
class PropertyRecord:
    index:int
    node:object
    fields:tuple

    @property
    def kind(self):return PropertyType(self)


@dataclass
class Access:
    member:object
    owner:object
    callbacks:dict
    result:object


class Properties:
    def __init__(self,model):
        self.model=model;self.records=[];self.constructors={};self.accesses={}
        from .native_owned_kinds import register
        register(model,lambda:(record.kind for record in self.records))
        from .native_callback_effects import register as register_effects
        register_effects(model,lambda plan,node:any(key[:2]==(plan.index,id(node))for key in self.accesses))

    def snapshot(self):
        from .native_classes import shape
        return tuple(tuple(shape(value)for value in record.fields)for record in self.records)

    def record(self,plan,node,identity=None):
        key=plan.index,id(node),identity
        record=self.constructors.get(key)
        if record is None:
            from .native_classes import Cell
            record=PropertyRecord(len(self.records),node,tuple(Cell()for _ in range(4)))
            self.records.append(record);self.constructors[key]=record
        return record

    def construct(self,plan,node,values,identity=None):
        from .native_classes import Cell,ClassUnsupported,shape,domain
        from .native_aot_callables import function_kind
        record=self.record(plan,node,identity)
        for name,value in zip(('fget','fset','fdel','doc'),values):
            kind=shape(value)
            if name=='fget'and kind is not None:
                # A custom callable can execute __getattribute__ while property
                # obtains its implicit doc. Sealed source/builtin callables and
                # builtin values have no such source callback.
                for branch in alternatives(kind):
                    if not function_kind(branch)and domain(branch)not in {'none','int','bool','int_bool','float','str','bytes','tuple','tuple_sequence','list'}:
                        raise ClassUnsupported(node,'property getter construction needs this callable object\'s __doc__/__getattribute__ and retained invocation protocols; only sealed compiled callables and closed builtin values are supported',types=(('fget',branch),),proof='property getter metadata and callable ownership')
        for target,value in zip(record.fields,values):
            if not self.model.namespace.contribute(target,value,node,force=True):self.model.contribute(target,value,node)
        return Cell(record.kind)

    def emit_construct(self,emitter,node,values,identity=None):
        from .native_classes import Expression,shape
        record=self.constructors[emitter.plan.index,id(node),identity]
        fields=','.join(name+':'+emitter.coerce(value,shape(target),node)for name,target,value in zip(('fget','fset','fdel','doc'),record.fields,values))
        code='Rc::new(ClassProperty_'+str(record.index)+'{'+fields+',name:RefCell::new(None)})'
        return Expression(code,record.kind)

    def property_member(self,plan,node,owner):
        from .native_classes import InstanceType,shape,ClassUnsupported
        kind=shape(owner)
        if not isinstance(kind,InstanceType):
            for branch in alternatives(kind):
                if not isinstance(branch,InstanceType):continue
                declaration=self.model.classes[branch.name]
                member=self.model.class_namespaces.members.get((declaration.index,self.model.resolved_name(plan,node)))
                if member is None:continue
                current=self.model.namespace.cells.get(member.key)
                if member.descriptor=='property'or current is not None and any(isinstance(item,PropertyType)for item in alternatives(shape(current))):
                    raise ClassUnsupported(node,'this finite receiver union includes a property data descriptor; per-receiver getter/setter/deleter projection and missing-attribute alternatives are not implemented',types=(('receiver',kind),),proof='finite receiver property descriptor projection')
            return None
        declaration=self.model.classes[kind.name]
        member=self.model.class_namespaces.members.get((declaration.index,self.model.resolved_name(plan,node)))
        if member is None:return None
        value=self.model.class_namespaces.field(member,node)
        kinds=alternatives(shape(value))
        if not any(isinstance(item,PropertyType)for item in kinds):return None
        if not all(isinstance(item,PropertyType)for item in kinds):
            raise ClassUnsupported(node,'this class slot mixes a property descriptor with ordinary values; per-value descriptor replacement and instance dictionary fallback are not implemented',types=(('class slot',shape(value)),),proof='fixed property data-descriptor precedence')
        return member,value

    def access(self,plan,node,owner,environment,slot='fget',value=None):
        self.accesses.pop((plan.index,id(node),slot),None)
        found=self.property_member(plan,node,owner)
        if found is None:return None
        member,descriptor=found
        from .native_classes import Cell,shape,ClassUnsupported
        from .native_aot_callables import analyze_values
        from .call_semantics import CallArguments,Argument
        from .native_guard_flow import AnalysisPending
        result=self.model.cell(plan,node,identity=('property_access',slot));callbacks={}
        arguments=[owner]+([]if value is None else[value])
        index={'fget':0,'fset':1,'fdel':2}[slot]
        for kind in alternatives(shape(descriptor)):
            source=kind.record.fields[index]
            if shape(source)is None:
                if not self.model.final:raise AnalysisPending()
                raise ClassUnsupported(node,'property '+slot+' payload remains unresolved',proof='resolved property callback payload')
            choices=[item for item in alternatives(shape(source))if item!='none']
            if not choices:
                self.model.contribute(result,Cell(EMPTY),node)
                continue
            source=Cell('union',tuple(self.model.cell_for_kind(item)for item in choices))if len(choices)>1 else self.model.cell_for_kind(choices[0])
            callback=analyze_values(self.model.callable_cells,plan,node,source,
                CallArguments(tuple(Argument(node)for _ in arguments),()),arguments,[],environment,
                identity=('property_callback',slot,kind.record.index))
            callbacks[kind]=callback
            if not self.model.namespace.contribute(result,callback.result,node,force=True):self.model.contribute(result,callback.result,node)
        self.accesses[plan.index,id(node),slot]=Access(member,self.model.flow_copy(owner),callbacks,result)
        if slot=='fget':return self.model.remember(plan,node,result)
        self.model.remember(plan,node,value if value is not None else Cell('none'))
        return result

    def emit_access(self,emitter,node,owner,slot='fget',value=None,wanted=None):
        from .native_classes import Expression,shape
        from .native_module_linking import ClassReferenceType
        from .native_aot_callables import emit_values
        from .native_unions import project
        from .native import _string
        site=self.accesses.get((emitter.plan.index,id(node),slot))
        if site is None:return None
        member=site.member;context=emitter.fresh()
        setup='let '+context+'={'+owner.code+'.borrow().class_definition.clone()};'
        descriptor=emitter.model.class_namespaces.emit_get(emitter,node,Expression(context,ClassReferenceType(member.owner.index)),member,instance=True)
        before,descriptor=emitter.capture(descriptor);setup+=before
        raw=shape(site.result)
        wanted=(wanted or emitter.kind(node))if slot=='fget'else'none'
        index={'fget':0,'fset':1,'fdel':2}[slot]
        noun={'fget':'getter','fset':'setter','fdel':'deleter'}[slot]
        arguments=[Expression('('+owner.code+').clone()',owner.kind)]+([]if value is None else[value])
        def property_branch(kind,code):
            getter=Expression('('+code+').'+slot+'.clone()',shape(kind.record.fields[index]))
            def callback_branch(source,payload):
                if source=='none':
                    message='format!("AttributeError: property \'{}\' of '+repr(member.owner.node.name)+' object has no '+noun+'",('+code+').name.borrow().as_deref().unwrap_or('+_string(member.name)+'))'
                    return emitter.at('Err::<'+emitter.rust_type(wanted)+',String>('+message+')',node)
                callback=site.callbacks[kind]
                result=emit_values(emitter,node,callback,Expression('('+payload+').clone()',source),arguments,[],raw)
                if slot!='fget':return '{'+result.code+';()}'
                return emitter.coerce(result,wanted,node)
            return project(getter.kind,getter.code,callback_branch)
        return Expression('{'+setup+project(descriptor.kind,descriptor.code,property_branch)+'}',wanted)

    def captured_store(self,plan,node,value,environment):
        site=self.accesses.get((plan.index,id(node),'fget'))
        if site is None:return False
        self.access(plan,node,site.owner,environment,'fset',value)
        return True

    def final_names(self,owner):
        scope=self.model.unit.scope_for(owner.node).ordinal;names={}
        rows=sorted((row for row in self.model.unit.bindings if row.owner==scope and row.role in {'definition','store','delete'}),key=lambda row:row.node)
        for row in rows:
            if row.role=='delete':names.pop(row.name,None)
            else:names.setdefault(row.name,None)
        return tuple(names)

    def emit_publication(self,emitter,owner):
        from .native_classes import shape
        from .native_unions import project
        from .native import _string
        code=''
        for name in self.final_names(owner):
            member=emitter.model.class_namespaces.members.get((owner.index,name))
            if member is None:continue
            if member.key not in emitter.model.namespace.active:continue
            stored=shape(emitter.model.namespace.cells[member.key])
            if not any(isinstance(kind,PropertyType)for kind in alternatives(stored)):continue
            scope=self.model.unit.scope_for(owner.node).ordinal
            owners=self.model.namespace.owners
            for child in ast.walk(owner.node):
                if not isinstance(child,ast.NamedExpr):continue
                binding=owners.get(self.model.unit.ordinal(child.target))
                if binding is not None and binding.owner==scope:
                    from .native_classes import ClassUnsupported
                    raise ClassUnsupported(child,'property __set_name__ needs the runtime insertion order of class assignment-expression bindings; that class publication order adapter is not implemented',proof='property class namespace insertion order')
            index=emitter.model.namespace.index(member.key);temporary=emitter.fresh()
            branch=lambda kind,value:'{*('+value+').name.borrow_mut()=Some('+_string(name)+'.to_owned());}'if isinstance(kind,PropertyType)else'()'
            code+='if let Some('+temporary+')={class_scope.globals.borrow().value_'+str(index)+'.clone()}{'+project(stored,temporary,branch)+'}'
        return code

    def validate(self):
        from .native_classes import ClassUnsupported,shape
        def visit(kind,path):
            if isinstance(kind,PropertyType):
                if kind.record.index in path:
                    raise ClassUnsupported(kind.record.node,'recursive property payload ownership needs a cycle-aware descriptor collector; this native property carrier requires a finite ownership layout',proof='acyclic property payload ownership')
                for child in kind._native_owned_kinds:visit(child,path|{kind.record.index})
            else:
                from .native_class_identity_demand import children
                for child in children(kind):
                    if child is not None:visit(child,path)
        for record in self.records:
            for value in record.fields:
                if shape(value)is None:raise ClassUnsupported(record.node,'property payload kind remains unresolved',proof='finite property payload storage')
                self.model.storage(value,record.node)
            visit(record.kind,set())

    def add_lifetime_edges(self,edges,targets):
        from .native_classes import shape
        if not hasattr(self.model,'class_namespaces'):return
        for owner in self.model.classes.values():
            key=('property_class_reference',owner.index)
            edges[key]=set()
            for (index,name),member in self.model.class_namespaces.members.items():
                if index!=owner.index or member.key not in self.model.namespace.active:continue
                kind=shape(self.model.namespace.cells[member.key])
                # A retained class reference can reach descriptors through
                # containers or instance-valued class data as well as a direct
                # property slot. Keep the entire actual class-data edge.
                edges[key].update(targets(kind))
            if('object',self.model.class_key(owner))in edges:
                edges['object',self.model.class_key(owner)].add(key)

    def runtime(self,emitter):
        from .native_classes import shape
        result=[]
        for record in self.records:
            fields=','.join(name+':'+emitter.rust_type(shape(value))for name,value in zip(('fget','fset','fdel','doc'),record.fields))
            result.append('struct ClassProperty_'+str(record.index)+'{'+fields+',name:RefCell<Option<String>>}')
        return '\n'.join(result)


def registry(model):
    if not hasattr(model,'properties'):model.properties=Properties(model)
    return model.properties


def bind(arguments,keywords,default):
    fields=('fget','fset','fdel','doc')
    count=len(arguments)+len(keywords)
    if count>4:return None,'TypeError: property() takes at most 4 arguments ('+str(count)+' given)'
    supplied=dict(keywords)
    for index,name in enumerate(fields[:len(arguments)]):
        if name in supplied:return None,'TypeError: argument for property() given by name ('+repr(name)+') and position ('+str(index+1)+')'
    result=dict(zip(fields,arguments))
    for name,value in keywords:
        if name not in fields:return None,'TypeError: property() got an unexpected keyword argument '+repr(name)
        result[name]=value
    return tuple(result.get(name,default)for name in fields),None


def analyze_constructor(model,plan,node,arguments,keywords,*,identity=None):
    from .native_classes import Cell
    values,error=bind(arguments,keywords,Cell('none'))
    if error:return model.cell(plan,node,EMPTY)
    return model.remember(plan,node,registry(model).construct(plan,node,values,identity))


def emit_constructor(emitter,node,arguments,keywords,wanted,*,identity=None):
    from .native_classes import Expression
    values,error=bind(arguments,list(keywords.items()),Expression('()','none'))
    if error:
        from .native import _string
        return Expression(emitter.at('Err::<'+emitter.rust_type(wanted)+',String>('+_string(error)+'.to_owned())',node),wanted)
    value=registry(emitter.model).emit_construct(emitter,node,values,identity)
    return Expression(emitter.coerce(value,wanted,node),wanted)


def snapshot(model):return model.properties.snapshot()if hasattr(model,'properties')else()
def validate(model):
    if hasattr(model,'properties'):model.properties.validate()
def runtime(model,emitter):return model.properties.runtime(emitter)if hasattr(model,'properties')else''


def requires_frames(analysis):
    from .references import BuiltinIdentity
    return any(BuiltinIdentity('property')in call.identity.alternatives for facts in analysis.scopes.values()for call in facts.calls.values())


def captured_store(model,plan,node,value,environment):
    return hasattr(model,'properties')and model.properties.captured_store(plan,node,value,environment)


def metadata_guard(node,kind,operation='reading'):
    if any(isinstance(branch,PropertyType)for branch in alternatives(kind)):
        from .native_classes import ClassUnsupported
        raise ClassUnsupported(node,operation+' property descriptor metadata '+repr(node.attr)+' requires its metadata/update-object protocol; that property metadata operation is not implemented',types=(('receiver',kind),),proof='property object metadata and update methods')


def comparison(operator,left,right):
    if isinstance(left.kind,PropertyType)and isinstance(right.kind,PropertyType):
        if isinstance(operator,(ast.Eq,ast.NotEq,ast.Is,ast.IsNot)):
            equal='(Rc::as_ptr(&('+left.code+'))as usize)==(Rc::as_ptr(&('+right.code+'))as usize)'
            return '!('+equal+')'if isinstance(operator,(ast.NotEq,ast.IsNot))else equal
    return None
