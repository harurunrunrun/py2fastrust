"""Registered shared builtin deque handles for independently typed frames."""
from dataclasses import dataclass,field
from .call_semantics import FunctionSignature,CallBindingError,normalize_call
from .native_types import EMPTY,alternatives

CONSTRUCTOR=FunctionSignature.declaration(('iterable','maxlen'),default_names=('iterable','maxlen'))
METHODS={'append':('value',),'appendleft':('value',),'pop':(),'popleft':(),'clear':(),'copy':()}

@dataclass(frozen=True)
class DequeType:
    index:int
    record:object=field(compare=False,hash=False,repr=False)
    _native_reference_cloneable=True
    _native_class_deque=True
    @property
    def _native_kind_tag(self):return 'class_deque_'+str(self.index)
    @property
    def element(self):
        from .native_classes import shape
        return shape(self.record.element)
    @property
    def _native_owned_kinds(self):
        from .native_classes import shape
        return (shape(self.record.element),)

@dataclass
class DequeRecord:
    index:int
    node:object
    plan:object
    element:object
    emitted:bool=False
    @property
    def kind(self):return DequeType(self.index,self)

@dataclass
class DequeSite:
    owner:object
    name:str
    binding:object=None
    source_type:object=None

class Deques:
    def __init__(self,model):
        self.model=model;self.records=[];self.allocations={};self.sites={}
        from .native_class_deque_indexing import Indexes
        self.indexes=Indexes(self)
    def owns(self,kind):return isinstance(kind,DequeType)and kind.index<len(self.records)and self.records[kind.index]is kind.record
    def snapshot(self):
        from .native_classes import shape
        return tuple(shape(record.element)for record in self.records)
    def default_uninhabited(self):
        from .native_classes import Cell,merge
        for record in self.records:
            if record.element.root().tag is None:merge(record.element,Cell(EMPTY),record.node)
    def validate(self,kind,node,seen):
        from .native_classes import ClassUnsupported
        from .native_class_storage import validate
        marker=('deque',kind.index)
        if not self.owns(kind):raise ClassUnsupported(node,'this deque handle has no registered allocation family',proof='registered deque ownership')
        if marker in seen:raise ClassUnsupported(node,'these deque elements permit a recursive shared ownership layout; cycle-aware deque storage is not implemented',proof='finite deque element layout and cycle-aware lifetime')
        validate(kind.record.element,node,self.model.integer,seen=seen|{marker},model=self.model)
    def add_lifetime_edges(self,edges,targets):
        for record in self.records:
            edges[('deque',record.index)]={target for child in record.kind._native_owned_kinds if child is not None for target in targets(child)}
    def _contribute(self,target,value,node):
        if not self.model.namespace.contribute(target,value,node,force=True):self.model.contribute(target,value,node)
    def element(self,kind):return kind.record.element if isinstance(kind,DequeType)else None
    def _binding(self,node,signature,metadata):
        from .native_classes import ClassUnsupported
        try:return signature.plan(metadata)
        except CallBindingError as error:raise ClassUnsupported(node,'this deque call needs its C-API signature-error transport: '+str(error),proof='deque captured call binding')from None
    def construct(self,plan,node,metadata,arguments,keywords,environment,factory):
        from .native_classes import Cell,shape,ClassUnsupported,domain
        key=plan.index,id(node)
        if key not in self.allocations:
            record=DequeRecord(len(self.records),node,plan,Cell());self.allocations[key]=record;self.records.append(record)
        record=self.allocations[key];binding=self._binding(node,CONSTRUCTOR,metadata)
        values=iter(arguments+[value for _,value in keywords])
        bound=binding.capture(lambda expression,parameter:next(values),defaults={'iterable':None,'maxlen':Cell('none')}).by_name
        for kind in alternatives(shape(bound['maxlen'])):
            if kind is not None and domain(kind)not in {'int','bool','int_bool','none','float','str','bytes','list','tuple','tuple_sequence','range','function'}:
                raise ClassUnsupported(node,'deque maxlen needs this value\'s __index__ protocol; that index conversion adapter is not implemented',types=(('maxlen',kind),),proof='deque maximum length index conversion')
        site=DequeSite(Cell(record.kind),'construct',binding)
        source=bound['iterable']
        if source is not None:
            if getattr(shape(source),'_native_class_generator',False):item=self.model.generators.demand(plan,node,source,environment)
            else:
                site.source_type=self.model.iterators.source(plan,node,source)
                item=self.model.iterators.demand(plan,node,Cell(site.source_type),environment)
            self._contribute(record.element,item,node)
        self.sites[key]=site
        return factory(record.kind)
    def analyze_attribute(self,plan,node,receiver):
        from .native_classes import Cell,shape,ClassUnsupported
        kinds=alternatives(shape(receiver))
        if not kinds or not all(isinstance(kind,DequeType)for kind in kinds):return None
        if node.attr!='maxlen':raise ClassUnsupported(node,'deque attribute '+repr(node.attr)+' needs a bound builtin method or deque-specific attribute adapter; only direct supported method calls and readonly maxlen are implemented',proof='stored deque attribute/method protocol')
        return self.model.cell(plan,node,'union',(Cell('int'),Cell('none')))
    def analyze_method(self,plan,node,receiver,arguments,keywords,environment):
        from .native_classes import Cell,shape,ClassUnsupported
        kinds=alternatives(shape(receiver))
        if not kinds or not all(isinstance(kind,DequeType)for kind in kinds):return None
        name=node.func.attr
        if name not in METHODS:raise ClassUnsupported(node,'deque.'+name+' needs its shared deque operation/cursor adapter; this typed frame slice implements append, appendleft, pop, popleft, clear and copy',proof='registered deque method protocol')
        parameters=METHODS[name];binding=self._binding(node,FunctionSignature.declaration(parameters,positional_only=parameters),normalize_call(node))
        if name in {'append','appendleft'}:
            for kind in kinds:self._contribute(kind.record.element,arguments[0],node)
            result=self.model.cell(plan,node,'none')
        elif name in {'pop','popleft'}:
            result=self.model.cell(plan,node)
            for kind in kinds:self._contribute(result,kind.record.element,node)
        elif name=='copy':result=self.model.cell(plan,node);self._contribute(result,receiver,node)
        else:result=self.model.cell(plan,node,'none')
        self.sites[(plan.index,id(node))]=DequeSite(receiver,name,binding)
        return result
    def rust_type(self,emitter,kind):
        from .native_classes import shape
        return 'Rc<RefCell<NativeDeque<'+emitter.rust_type(shape(kind.record.element))+'>>>'
    def truth(self,emitter,value):return '!('+value.code+').borrow().is_empty()'
    def show(self,emitter,value,node):
        from .native_classes import Expression,shape
        owner,item,result=emitter.fresh(),emitter.fresh(),emitter.fresh()
        text=emitter.show(Expression(item+'.clone()',shape(value.kind.record.element)),node,True)
        return '{let '+owner+'=('+value.code+').clone();let '+result+'=native_deque_repr_with(&'+owner+'.borrow(),|'+item+'|'+text+');'+result+'}'
    def emit_attribute(self,emitter,node,value,wanted):
        from .native_classes import Expression
        from .native_unions import project,construct
        def leaf(kind,text):
            code='('+text+').borrow().maxlen'
            return code+'.map(|value|class_from_usize(value))'
        return Expression(project(value.kind,value.code,leaf),wanted)
    def _maxlen(self,emitter,node,value):
        from .native_classes import Expression
        from .native_unions import project
        from .native import _string
        def leaf(kind,text):
            if kind=='none':return 'None'
            if kind not in {'int','bool','int_bool'}:return emitter.at('Err::<Option<usize>,String>("TypeError: an integer is required".to_owned())',node)
            number=emitter.number(Expression('('+text+').clone()',kind))
            wide='('+number+').to_i128()'if self.model.integer=='bigint'else'Some(('+number+')as i128)'
            size=emitter.at('('+wide+').and_then(|value|isize::try_from(value).ok()).ok_or_else(||"OverflowError: Python int too large to convert to C ssize_t".to_owned())',node)
            return 'Some('+emitter.at('native_deque_maxlen('+size+')',node)+')'
        return project(value.kind,value.code,leaf)
    def _consume(self,emitter,node,owner,source,site):
        from .native_classes import Expression,shape
        def append(current,item):
            value=current.coerce(item,shape(owner.kind.record.element),node)
            return current.at('('+owner.code+').borrow_mut().push_back('+value+')',node)+';'
        if getattr(source.kind,'_native_class_generator',False):
            return self.model.generators.consume(emitter,node,'eager_member',source,[source],{},'none',append_item=append).code+';'
        from .native_class_iterators import iterator_kind
        if iterator_kind(source.kind):before,iterator='',source
        else:before,iterator=emitter.capture(self.model.iterators.construct(emitter,node,source,kind=site.source_type))
        pulled=self.model.iterators.pull(emitter,node,iterator);item=emitter.fresh()
        return before+'loop{let Some('+item+')=('+pulled.code+')else{break;};'+append(emitter,Expression(item,pulled.kind))+'}'
    def emit_constructor(self,emitter,node,arguments,keywords,wanted):
        from .native_classes import Expression,shape
        site=self.sites[(emitter.plan.index,id(node))];record=wanted.record;record.emitted=True
        values=iter(arguments+[value for _,value in keywords])
        bound=site.binding.capture(lambda expression,parameter:next(values),defaults={'iterable':None,'maxlen':Expression('()','none')}).by_name
        owner=emitter.fresh();code='let '+owner+'=Rc::new(RefCell::new(NativeDeque::<'+emitter.rust_type(shape(record.element))+'>::new('+self._maxlen(emitter,node,bound['maxlen'])+')));'
        if bound['iterable']is not None:code+=self._consume(emitter,node,Expression(owner,wanted),bound['iterable'],site)
        return Expression('{'+code+owner+'}',wanted)
    def emit_method(self,emitter,node):
        from .native_classes import Expression,shape
        from .native_unions import project
        site=self.sites.get((emitter.plan.index,id(node)))
        if site is None or site.name=='construct':return None
        before,owner=emitter.capture(emitter.expression(node.func.value));arguments=[]
        for value in normalize_call(node).evaluation_order:
            setup,item=emitter.capture(emitter.expression(value.expression));before+=setup;arguments.append(item)
        wanted=emitter.kind(node)
        def leaf(kind,text):
            owner,read=emitter.fresh(),emitter.fresh();prefix='let '+owner+'=('+text+').clone();'
            if site.name in {'append','appendleft'}:
                item=emitter.coerce(arguments[0],shape(kind.record.element),node)
                code=emitter.at(owner+'.borrow_mut().push_'+('front'if site.name=='appendleft'else'back')+'('+item+')',node);raw='none'
            elif site.name in {'pop','popleft'}:
                code=emitter.at(owner+'.borrow_mut().values.pop_'+('front'if site.name=='popleft'else'back')+'().ok_or_else(||"IndexError: pop from an empty deque".to_owned())',node);raw=shape(kind.record.element)
            elif site.name=='clear':code=owner+'.borrow_mut().clear()';raw='none'
            else:code='Rc::new(RefCell::new('+emitter.at('native_deque_mapped_copy(&'+owner+'.borrow(),|value|value.clone())',node)+'))';raw=kind
            result=emitter.coerce(Expression(code,raw),wanted,node)
            return '{'+prefix+'let '+read+'='+result+';'+read+'}'
        return Expression('{'+before+project(owner.kind,owner.code,leaf)+'}',wanted)
    def runtime(self):
        if not any(record.emitted for record in self.records):return ''
        from .native_deques import HELPERS
        return HELPERS


def requires_frames(unit,analysis):
    import ast
    from .native_types import DequeType as OrdinaryDeque,immutable
    def deque(kind):return kind=='deque_int'or isinstance(kind,OrdinaryDeque)
    kinds={}
    for(definition,arguments),facts in analysis.scopes.items():
        if definition is not None and any(deque(kind)for kind in arguments):return True
        for site,kind in facts.expressions.items():kinds.setdefault(site,[]).append(kind)
    for node in ast.walk(unit.tree):
        if isinstance(node,ast.Assign):
            source=kinds.get(unit.ordinal(node.value),())
            if not any(deque(kind)for kind in source):continue
            if len(node.targets)>1:return True
            if isinstance(node.value,ast.Name)and any(isinstance(target,ast.Name)and unit.name_for(target)!=unit.name_for(node.value)for target in node.targets):return True
        if any(isinstance(kind,OrdinaryDeque)and not immutable(kind.element)for kind in kinds.get(unit.ordinal(node),())):return True
    return False
