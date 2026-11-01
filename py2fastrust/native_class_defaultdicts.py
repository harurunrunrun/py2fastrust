"""Typed defaultdict factories and missing reads over shared native storage."""
import ast
from dataclasses import dataclass,field
from .native_types import alternatives


@dataclass
class DefaultSite:
    record:object
    source:object=None
    source_type:object=None
    calls:dict=field(default_factory=dict)


def is_default(kind):
    return bool(getattr(kind,'_native_class_mapping',False)and kind.record.flavor=='defaultdict')


class DefaultDicts:
    def __init__(self,mappings):
        self.mappings=mappings;self.model=mappings.model;self.sites={};self.calls={};self.filtered={}
        from .native_callback_effects import register
        register(self.model,self.effects)

    def construct(self,plan,node,arguments,keywords,environment,factory):
        from .native_classes import Cell,shape,ClassUnsupported
        if len(arguments)>2:raise ClassUnsupported(node,'defaultdict accepts a default factory and at most one initial mapping/iterable; this constructor binding is not represented',proof='defaultdict constructor signature')
        record=self.mappings.record(plan,node,'dict','defaultdict',flavor='defaultdict')
        if record.default_factory is None:record.default_factory=Cell()
        supplied=arguments[0]if arguments else Cell('none')
        self.model.contribute(record.default_factory,supplied,node)
        site=DefaultSite(record);self.sites[(plan.index,id(node))]=site
        if len(arguments)>1:
            source=arguments[1];site.source=source
            self._initial(plan,node,site,source,environment)
        for name,value in keywords:
            self.mappings.contribute_key(record,Cell('str'),node)
            self.model.contribute(record.value,value,node)
        return factory(record.kind)

    def _initial(self,plan,node,site,source,environment):
        from .native_classes import Cell,shape,ClassUnsupported
        from .native_class_mappings import mapping_kind
        kinds=alternatives(shape(source));record=site.record
        if kinds and all(mapping_kind(kind)and kind.record.category=='dict'for kind in kinds):
            for kind in kinds:
                self.mappings.contribute_key(record,kind.record.key,node)
                self.model.contribute(record.value,kind.record.value,node)
            return
        if getattr(shape(source),'_native_class_generator',False):
            item=self.model.generators.demand(plan,node,source,environment).root()
        else:
            site.source_type=self.model.iterators.source(plan,node,source)
            item=self.model.iterators.demand(plan,node,Cell(site.source_type),environment).root()
        if item.tag=='tuple'and len(item.args)==2:
            self.mappings.contribute_key(record,item.args[0],node)
            self.model.contribute(record.value,item.args[1],node)
        elif shape(item)is not None:
            raise ClassUnsupported(node,'defaultdict initial iterable needs typed two-element update pairs; generic element unpacking has no defaultdict update adapter',types=(('element',shape(item)),),proof='defaultdict initial dictionary update pairs')

    def analyze_get(self,plan,node,record,index,environment):
        from .native_classes import Cell,shape,Environment
        from .native_aot_callables import function_kind,analyze_values
        from .native_class_mappings import key_supported
        from .call_semantics import CallArguments
        if record.flavor!='defaultdict':return
        kind=shape(index)
        if kind is not None and not key_supported(kind):return
        choices=[kind for kind in alternatives(shape(record.default_factory))if function_kind(kind)]
        if not choices:return
        self.mappings.contribute_key(record,index,node)
        key=record.index
        filtered=self.filtered.setdefault(key,Cell())
        for kind in choices:self.model.contribute(filtered,self.model.cell_for_kind(kind),node)
        inside=Environment(environment)
        site=analyze_values(self.model.callable_cells,plan,node,filtered,CallArguments((),()),[],[],inside,identity=('defaultdict_factory',record.index))
        self.calls[(plan.index,id(node),record.index)]=site
        self.model.contribute(record.value,site.result,node)
        self.model.replace_environment(environment,self.model.join(environment,inside,node,'defaultdict_missing'))

    def attribute(self,plan,node,receiver,environment):
        from .native_classes import shape
        kinds=alternatives(shape(receiver))
        if node.attr!='default_factory'or not kinds or not all(is_default(kind)for kind in kinds):return None
        result=self.model.cell(plan,node)
        for kind in kinds:self.model.contribute(result,kind.record.default_factory,node)
        return self.model.remember(plan,node,result)

    def attribute_store(self,plan,node,receiver,value):
        from .native_classes import shape
        kinds=alternatives(shape(receiver))
        if node.attr!='default_factory'or not kinds or not all(is_default(kind)for kind in kinds):return False
        for kind in kinds:self.model.contribute(kind.record.default_factory,value,node)
        result=self.attribute(plan,node,receiver,None)
        self.model.remember(plan,node,result)
        return True

    def copy_record(self,record,old,node):
        from .native_classes import Cell
        if old.flavor!='defaultdict':return
        if record.default_factory is None:record.default_factory=Cell()
        self.model.contribute(record.default_factory,old.default_factory,node)

    def pending_value(self,record):
        return any(index==record.index and site.result.root().tag is None for (plan,node,index),site in self.calls.items())

    def effects(self,plan,node):
        return any(index==plan.index and ordinal==id(node)and(bool(site.targets)or bool(site.members))for (index,ordinal,record),site in self.calls.items())

    def new(self,emitter,record,factory):
        from .native_classes import shape
        from .native_class_mappings import canonical_type
        key,value=shape(record.key),shape(record.value)
        data='NativeKeyDict::<'+emitter.rust_type(key)+','+emitter.rust_type(value)+','+canonical_type(key)+'>::new()'
        converted=emitter.coerce(factory,shape(record.default_factory),record.node)
        return 'Rc::new(ClassDefaultState_'+str(record.index)+'{data:RefCell::new('+data+'),factory:RefCell::new('+converted+')})'

    def emit_constructor(self,emitter,node,arguments,keywords,wanted):
        from .native_classes import Expression
        from .native_aot_callables import function_kind
        from .native_unions import project,union_kind
        from .native_class_builtins import _error
        record=wanted.record;record.emitted=True
        supplied=arguments[0]if arguments else Expression('()','none')
        def build(kind,text):
            if kind!='none'and not function_kind(kind):
                from .native_classes import ClassUnsupported,domain
                if domain(kind)=='object'or type(kind).__name__=='ClassReferenceType':
                    raise ClassUnsupported(node,'this default factory needs a user class/callable-object constructor protocol; a captured zero-argument callable ABI is not implemented for this object',types=(('factory',kind),),proof='captured default factory callable protocol')
                return _error(emitter,node,wanted,'"TypeError: first argument must be callable or None".to_owned()').code
            owner=emitter.fresh();code='let '+owner+'='+self.new(emitter,record,Expression('('+text+').clone()',kind))+';'
            if len(arguments)>1:code+=self._emit_initial(emitter,node,Expression(owner,wanted),arguments[1],self.sites[(emitter.plan.index,id(node))])
            from .native import _string
            for key,value in keywords:code+=self.mappings._set(emitter,node,Expression(owner,wanted),Expression('NativeText::from('+_string(key)+')','str'),value)
            return '{'+code+owner+'}'
        code=project(supplied.kind,supplied.code,build)if union_kind(supplied.kind)else build(supplied.kind,supplied.code)
        return Expression(code,wanted)

    def _emit_initial(self,emitter,node,owner,source,site):
        from .native_classes import Expression,shape
        from .native_class_mappings import mapping_kind
        from .native_unions import project,union_kind
        if getattr(source.kind,'_native_class_generator',False):
            def append(e,pair):
                return self.mappings._set(e,node,owner,Expression(pair.code+'.0',pair.kind.fields[0]),Expression(pair.code+'.1',pair.kind.fields[1]))
            return self.model.generators.consume(emitter,node,'defaultdict',source,[],{},'none',append_item=append).code+';'
        if mapping_kind(source.kind):
            cursor,pair=(emitter.fresh()for _ in range(2));old=source.kind.record
            pulled=emitter.at(cursor+'.next(|key,value|(key.clone(),value.clone()))',node)
            return '{let mut '+cursor+'=ClassMappingCursor::new('+source.code+');loop{let Some('+pair+')=('+pulled+')else{break;};'+self.mappings._set(emitter,node,owner,Expression(pair+'.0',shape(old.key)),Expression(pair+'.1',shape(old.value)))+'}}'
        if union_kind(source.kind):return project(source.kind,source.code,lambda kind,text:'{'+self._emit_initial(emitter,node,owner,Expression('('+text+').clone()',kind),site)+'}')+';'
        from .native_class_iterators import iterator_kind
        if iterator_kind(source.kind):before,iterator='',source
        else:before,iterator=emitter.capture(self.model.iterators.construct(emitter,node,source,kind=site.source_type))
        pulled=self.model.iterators.pull(emitter,node,iterator);pair=emitter.fresh()
        return before+'loop{let Some('+pair+')=('+pulled.code+')else{break;};'+self.mappings._set(emitter,node,owner,Expression(pair+'.0',pulled.kind.fields[0]),Expression(pair+'.1',pulled.kind.fields[1]))+'}'

    def missing(self,emitter,node,owner,key,wanted):
        from .native_classes import Expression,shape,ClassUnsupported
        from .native_aot_callables import function_kind,emit_values
        from .native_class_builtins import _error,_type_name
        from .native_unions import project,union_kind
        record=owner.kind.record;factory=emitter.fresh();read=emitter.fresh();kind=shape(record.default_factory)
        before='let '+factory+'={let '+read+'='+owner.code+'.factory.borrow().clone();'+read+'};'
        def branch(factory_kind,text):
            if factory_kind=='none':
                return _error(emitter,node,wanted,'format!("KeyError: {}",'+emitter.show(key,node,True)+')').code
            if not function_kind(factory_kind):
                return _error(emitter,node,wanted,'format!("TypeError: \'{}\' object is not callable",'+_type_name(emitter,Expression(text,factory_kind),node)+')').code
            site=self.calls.get((emitter.plan.index,id(node),record.index))
            if site is None:raise ClassUnsupported(node,'the missing-key factory has no proved zero-argument captured call site',proof='defaultdict captured factory demand')
            result=emit_values(emitter,node,site,Expression('('+text+').clone()',factory_kind),[],[],shape(site.result))
            captured,value=emitter.capture(result)
            from .native_class_mappings import canonical
            retained,hashed,found=(emitter.fresh()for _ in range(3));key_kind=shape(record.key);value_kind=shape(record.value)
            encoded=emitter.coerce(Expression('('+key.code+').clone()',key.kind),key_kind,node)
            hashed_key=canonical(emitter,Expression(retained,key_kind))
            inserted=emitter.at(owner.code+'.borrow_mut().set_default('+retained+','+hashed+','+emitter.coerce(value,value_kind,node)+')',node)
            return '{'+captured+'let '+retained+':'+emitter.rust_type(key_kind)+'='+encoded+';let '+hashed+'='+hashed_key+';let '+found+'='+inserted+';'+emitter.coerce(Expression(found,value_kind),wanted,node)+'}'
        code=project(kind,factory,branch)if union_kind(kind)else branch(kind,factory)
        return '{'+before+code+'}'

    def emit_attribute(self,emitter,node,owner,wanted):
        from .native_classes import Expression,shape
        from .native_unions import project,union_kind
        def branch(kind,text):
            stable,read,found=(emitter.fresh()for _ in range(3))
            value=Expression(found,shape(kind.record.default_factory))
            return '{let '+stable+'=('+text+').clone();let '+found+'={let '+read+'='+stable+'.factory.borrow().clone();'+read+'};'+emitter.coerce(value,wanted,node)+'}'
        return project(owner.kind,owner.code,branch)if union_kind(owner.kind)else branch(owner.kind,owner.code)

    def emit_attribute_store(self,emitter,node,owner,value):
        from .native_classes import shape
        from .native_unions import project,union_kind
        def branch(kind,text):
            stable=emitter.fresh();converted=emitter.coerce(value,shape(kind.record.default_factory),node)
            return '{let '+stable+'=('+text+').clone();*'+stable+'.factory.borrow_mut()='+converted+';}'
        return (project(owner.kind,owner.code,branch)if union_kind(owner.kind)else branch(owner.kind,owner.code))+';'

    def emit_copy(self,emitter,node,owner,wanted):
        from .native_classes import Expression,shape
        record=wanted.record;record.emitted=True
        data,factory=(emitter.fresh()for _ in range(2))
        value=Expression(factory,shape(owner.kind.record.default_factory))
        converted=emitter.coerce(value,shape(record.default_factory),node)
        return '{let '+data+'='+owner.code+'.borrow().clone();let '+factory+'='+owner.code+'.factory.borrow().clone();Rc::new(ClassDefaultState_'+str(record.index)+'{data:RefCell::new('+data+'),factory:RefCell::new('+converted+')})}'

    def show(self,emitter,value,node):
        from .native_classes import Expression,shape,ClassUnsupported
        from .native_unions import project,union_kind
        from .native_aot_callables import variant,function_kind
        record=value.kind.record;owner,factory,read=(emitter.fresh()for _ in range(3))
        before='let '+owner+'=('+value.code+').clone();let '+factory+'={let '+read+'='+owner+'.factory.borrow().clone();'+read+'};'
        kind=shape(record.default_factory);factory_text=emitter.show(Expression(factory,kind),node,True)
        key,item,read=(emitter.fresh()for _ in range(3))
        a=emitter.show(Expression(key+'.clone()',shape(record.key)),node,True);b=emitter.show(Expression(item+'.clone()',shape(record.value)),node,True)
        return '{'+before+'let factory_text='+factory_text+';let '+read+'='+owner+'.borrow();format!("defaultdict({}, {{{}}})",factory_text,'+read+'.entries.iter().map(|('+key+','+item+')|format!("{}: {}",'+a+','+b+')).collect::<Vec<_>>().join(", "))}'

    def owner_type(self,record):return 'ClassDefaultState_'+str(record.index)

    def runtime(self,emitter):
        from .native_classes import shape
        from .native_class_mappings import canonical_type
        result=[]
        for record in self.mappings.records:
            if record.flavor!='defaultdict':continue
            key,value=shape(record.key),shape(record.value)
            k,v,c=emitter.rust_type(key),emitter.rust_type(value),canonical_type(key)
            data='NativeKeyDict<'+k+','+v+','+c+'>';owner=self.owner_type(record)
            result.append('struct '+owner+'{data:RefCell<'+data+'>,factory:RefCell<'+emitter.rust_type(shape(record.default_factory))+'>}')
            result.append('impl std::ops::Deref for '+owner+'{type Target=RefCell<'+data+'>;fn deref(&self)->&Self::Target{&self.data}}')
            result.append('impl ClassMappingOwner for '+owner+'{type Key='+k+';type Value='+v+';type Canonical='+c+';fn mapping(&self)->&RefCell<'+data+'>{&self.data}}')
        return '\n'.join(result)
