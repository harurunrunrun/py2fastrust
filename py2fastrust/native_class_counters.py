"""Typed Counter operations over shared insertion-ordered native mappings."""
from dataclasses import dataclass
from .native_types import alternatives,EmptyType


class CollectionsAdapter:
    NAMES=frozenset({'Counter','defaultdict','deque'})
    TYPES=frozenset({'Counter','defaultdict','deque'})
    EAGER_ARGUMENTS={'Counter':frozenset({0}),'defaultdict':frozenset({1}),'deque':frozenset({0})}

    @staticmethod
    def eager_method_arguments(kind,name):
        if (getattr(kind,'_native_class_mapping',False)and kind.record.flavor=='Counter'
                and name in {'update','subtract'}):return frozenset({0})
        return None

    @staticmethod
    def match_type(emitter,node,value,name):
        from .native_classes import Expression
        from .native_unions import project,union_kind
        if union_kind(value.kind):
            return project(value.kind,value.code,lambda kind,text:CollectionsAdapter.match_type(emitter,node,Expression('('+text+').clone()',kind),name))
        if name=='deque':return str(getattr(value.kind,'_native_class_deque',False)).lower()
        return str(name in CollectionsAdapter.TYPES and getattr(value.kind,'_native_class_mapping',False)and value.kind.record.flavor==name).lower()

    @staticmethod
    def analyze(model,plan,node,identity,normalized_call,positional,keywords,environment,*,factory):
        from .native_linked_members import MemberCall
        if identity.name=='deque':return MemberCall(model.deques.construct(plan,node,normalized_call,positional,keywords,environment,factory))
        if identity.name=='defaultdict':return MemberCall(model.mappings.defaultdicts.construct(plan,node,positional,keywords,environment,factory))
        return MemberCall(model.mappings.counters.construct(plan,node,positional,keywords,environment,factory))

    @staticmethod
    def emit(emitter,node,identity,record,positional,keywords):
        from .native_classes import shape
        if identity.name=='deque':return emitter.model.deques.emit_constructor(emitter,node,positional,keywords,shape(record.result))
        if identity.name=='defaultdict':return emitter.model.mappings.defaultdicts.emit_constructor(emitter,node,positional,keywords,shape(record.result))
        return emitter.model.mappings.counters.emit_constructor(emitter,node,positional,keywords,shape(record.result))


@dataclass
class CounterSite:
    owner:object
    name:str
    source:object=None
    source_type:object=None
    mapping_source:bool=False


class Counters:
    def __init__(self,mappings):
        self.mappings=mappings;self.model=mappings.model;self.sites={}

    def validate(self,record,node):
        from .native_classes import shape,ClassUnsupported
        if record.flavor=='Counter'and shape(record.value)not in {'int','bool','int_bool'}:
            raise ClassUnsupported(node,'this Counter needs non-integral count comparison/addition protocols; only builtin integer/boolean counts have typed Counter operations',types=(('count',shape(record.value)),),proof='typed Counter count operations')

    def construct(self,plan,node,arguments,keywords,environment,factory):
        from .native_classes import Cell,ClassUnsupported
        if len(arguments)>1:raise ClassUnsupported(node,'Counter accepts at most one positional iterable; this invalid constructor binding requires its builtin class call error protocol',proof='Counter constructor signature')
        record=self.mappings.record(plan,node,'dict','Counter',flavor='Counter')
        self.model.contribute(record.value,Cell('int'),node)
        site=CounterSite(Cell(record.kind),'construct');self.sites[(plan.index,id(node))]=site
        if arguments:self._source(plan,node,site,arguments[0],environment)
        self._keywords(record,keywords,node)
        return factory(record.kind)

    def _keywords(self,record,keywords,node):
        from .native_classes import Cell
        for name,value in keywords:
            self.mappings.contribute_key(record,Cell('str'),node)
            self.model.contribute(record.value,value,node)

    def _source(self,plan,node,site,source,environment):
        from .native_classes import Cell,shape,ClassUnsupported
        from .native_class_mappings import mapping_kind
        site.source=source;kinds=alternatives(shape(source))
        owners=alternatives(shape(site.owner))
        if getattr(shape(source),'_native_class_generator',False):
            item=self.model.generators.demand(plan,node,source,environment)
            for owner in owners:self.mappings.contribute_key(owner.record,item,node)
            return
        ordinary=[]
        for kind in kinds:
            if kind=='none':continue
            if mapping_kind(kind)and kind.record.category=='dict':
                for owner in owners:
                    self.mappings.contribute_key(owner.record,kind.record.key,node)
                    self.model.contribute(owner.record.value,kind.record.value,node)
            else:ordinary.append(kind)
        site.mapping_source=bool(kinds)and not ordinary
        if ordinary or not kinds:
            site.source_type=self.model.iterators.source(plan,node,source)
            item=self.model.iterators.demand(plan,node,Cell(site.source_type),environment)
            for owner in owners:self.mappings.contribute_key(owner.record,item,node)

    def analyze_method(self,plan,node,receiver,arguments,keywords,environment):
        from .native_classes import Cell,shape,ClassUnsupported
        from .native_class_mappings import mapping_kind
        kinds=alternatives(shape(receiver));name=node.func.attr
        if not kinds or not all(mapping_kind(kind)and kind.record.flavor=='Counter'for kind in kinds):return None
        if name=='elements':
            raise ClassUnsupported(node,'Counter.elements requires a lazy repeated-key cursor with count snapshots and dictionary mutation checks; that iterator adapter is not implemented',types=(('receiver',shape(receiver)),),proof='Counter.elements pull-state protocol')
        if name not in {'update','subtract','total','most_common'}:return None
        if name in {'update','subtract'}:
            if len(arguments)>1:raise ClassUnsupported(node,'this Counter mutation accepts at most one positional iterable; the supplied method binding is not represented',proof='Counter mutation argument binding')
            site=CounterSite(receiver,name)
            if arguments:self._source(plan,node,site,arguments[0],environment)
            for kind in kinds:self._keywords(kind.record,keywords,node)
            result=self.model.cell(plan,node,'none')
        elif name=='total':
            if arguments or keywords:raise ClassUnsupported(node,'Counter.total takes no arguments; this method binding is not represented',proof='Counter.total argument binding')
            site=CounterSite(receiver,name);result=self.model.cell(plan,node,'int')
        else:
            if len(arguments)>1 or any(key!='n'for key,value in keywords)or arguments and keywords:
                raise ClassUnsupported(node,'Counter.most_common accepts one optional n argument; these supplied bindings are incompatible',proof='Counter.most_common argument binding')
            limit=arguments[0]if arguments else keywords[0][1]if keywords else Cell('none')
            limit_kind=shape(limit)
            if limit_kind is not None and any(kind not in {'int','bool','int_bool','none'}for kind in alternatives(limit_kind)):
                raise ClassUnsupported(node,'Counter.most_common n requires a builtin integer or None; custom index conversion is not implemented',types=(('n',limit_kind),),proof='Counter.most_common index conversion')
            site=CounterSite(receiver,name)
            result=self.model.cell(plan,node,'list',(Cell('tuple',(Cell(),Cell())),))
            key,value=result.root().args[0].root().args
            for kind in kinds:
                self.model.contribute(key,kind.record.key,node);self.model.contribute(value,kind.record.value,node)
        self.sites[(plan.index,id(node))]=site
        return result

    def emit_method(self,emitter,node):
        from .native_classes import Expression
        from .call_semantics import normalize_call
        from .native_unions import project,union_kind
        site=self.sites.get((emitter.plan.index,id(node)))
        if site is None or site.name=='construct':return None
        before,owner=emitter.capture(emitter.expression(node.func.value));arguments=[];keywords=[]
        for argument in normalize_call(node).evaluation_order:
            setup,value=emitter.capture(emitter.expression(argument.expression));before+=setup
            if argument.name is None:arguments.append(value)
            else:keywords.append((argument.name,value))
        wanted=emitter.kind(node)
        def branch(kind,text):
            captured,value=emitter.capture(Expression('('+text+').clone()',kind))
            return '{'+captured+self._emit_method(emitter,node,site,value,arguments,keywords,wanted)+'}'
        code=project(owner.kind,owner.code,branch)if union_kind(owner.kind)else branch(owner.kind,owner.code)
        return Expression('{'+before+code+'}',wanted)

    def _emit_method(self,emitter,node,site,owner,arguments,keywords,wanted):
        from .native_classes import Expression,shape
        from .native_types import TupleType
        if site.name in {'update','subtract'}:
            code=self._consume(emitter,node,owner,arguments[0],site,subtract=site.name=='subtract')if arguments else''
            if keywords:
                from .native import _string
                empty=emitter.fresh();code+='let '+empty+'='+owner.code+'.borrow().is_empty();'
                for key,amount in keywords:
                    code+=self._add(emitter,node,owner,Expression('NativeText::from('+_string(key)+')','str'),amount,subtract=site.name=='subtract',replace_if_empty=empty if site.name=='update'else None)
            return '{'+code+'()}'
        record=owner.kind.record
        if site.name=='total':
            import ast
            from .native_primitive_ops import emit
            accumulator,read,item=(emitter.fresh()for _ in range(3))
            addition=emit(emitter,ast.Add(),Expression(accumulator+'.clone()','int'),Expression(item+'.clone()',shape(record.value)),node,'int').code
            return '{let mut '+accumulator+'='+emitter.literal(0)+';let '+read+'='+owner.code+'.borrow();for(_,'+item+')in '+read+'.entries.iter(){'+accumulator+'='+addition+';}'+accumulator+'}'
        limit=arguments[0]if arguments else keywords[0][1]if keywords else Expression('()','none')
        from .native_unions import project,union_kind
        def rows_for(kind,text):
            rows,read,left,right=(emitter.fresh()for _ in range(4))
            if kind=='none':
                a=emitter.number(Expression(left+'.1.clone()',shape(record.value)))
                b=emitter.number(Expression(right+'.1.clone()',shape(record.value)))
                return '{let mut '+rows+'={let '+read+'='+owner.code+'.borrow();'+read+'.entries.iter().cloned().collect::<Vec<_>>()};'+rows+'.sort_by(|'+left+','+right+'|('+b+').cmp(&('+a+')));'+rows+'}'
            number=emitter.number(Expression('('+text+').clone()',kind))
            size,value,count=(emitter.fresh()for _ in range(3))
            offset=emitter.at('class_index(&'+value+','+size+')',node)
            rank=emitter.number(Expression('count.clone()',shape(record.value)))
            selected=emitter.at('class_counter_best(&'+read+'.entries,'+count+',|count|'+rank+')',node)
            return '{let '+value+'='+number+';let '+size+'='+owner.code+'.borrow().len();let '+count+'=if '+value+'<='+emitter.literal(0)+'{0}else if '+value+'>=class_from_usize('+size+'){'+size+'}else{'+offset+'};let '+read+'='+owner.code+'.borrow();'+selected+'}'
        code=project(limit.kind,limit.code,rows_for)if union_kind(limit.kind)else rows_for(limit.kind,limit.code)
        item=emitter.fresh();old=TupleType((shape(record.key),shape(record.value)))
        converted=emitter.coerce(Expression(item,old),wanted.element,node)
        return 'class_list(('+code+').into_iter().map(|'+item+'|'+converted+').collect::<Vec<_>>())'

    def _add(self,emitter,node,owner,key,amount,*,subtract=False,replace_if_empty=None):
        from .native_classes import Expression,shape
        from .native_primitive_ops import emit
        import ast
        record=owner.kind.record
        current=emitter.fresh();prior=self.mappings.emit_get(emitter,node,owner,key,shape(record.value)).code
        old=Expression(current,shape(record.value));wanted=shape(record.value)
        summed=emit(emitter,ast.Sub()if subtract else ast.Add(),old,amount,node,'int')
        value=Expression(summed.code,'int')
        updated='let '+current+'='+prior+';'+self.mappings._set(emitter,node,owner,key,value)
        if replace_if_empty is not None:
            updated='if '+replace_if_empty+'{'+self.mappings._set(emitter,node,owner,key,amount)+'}else{'+updated+'}'
        return updated

    def _consume(self,emitter,node,owner,source,site,*,subtract=False):
        from .native_classes import Expression,shape
        from .native_unions import project,union_kind
        if source.kind=='none':return ''
        if getattr(source.kind,'_native_class_generator',False):
            def append(current,item):
                return self._add(current,node,owner,item,Expression(current.literal(1),'int',1),subtract=subtract)
            return self.model.generators.consume(emitter,node,'eager_member',source,[source],{},'none',append_item=append).code+';'
        if union_kind(source.kind):
            from .native_class_mappings import mapping_kind
            def branch(kind,text):
                nested=CounterSite(site.owner,site.name,site.source,site.source_type,mapping_kind(kind)and kind.record.category=='dict')
                code=self._consume(emitter,node,owner,Expression('('+text+').clone()',kind),nested,subtract=subtract)
                return '{'+code+'}'
            return project(source.kind,source.code,branch)+';'
        if site.mapping_source:
            empty=emitter.fresh()if not subtract else None
            code='let '+empty+'='+owner.code+'.borrow().is_empty();'if empty else''
            def branch(kind,text):
                cursor,item,key,value=(emitter.fresh()for _ in range(4))
                key_kind=shape(kind.record.key);value_kind=shape(kind.record.value)
                pull=emitter.at(cursor+'.next(|key,value|(key.clone(),value.clone()))',node)
                body='let mut '+cursor+'=ClassMappingCursor::new(('+text+').clone());loop{let Some('+item+')=('+pull+')else{break;};let ('+key+','+value+')='+item+';'
                body+=self._add(emitter,node,owner,Expression(key,key_kind),Expression(value,value_kind),subtract=subtract,replace_if_empty=None if subtract else empty)
                return '{'+body+'}}'
            return code+(project(source.kind,source.code,branch)if union_kind(source.kind)else branch(source.kind,source.code))+';'
        from .native_class_iterators import iterator_kind
        if iterator_kind(source.kind):before,iterator='',source
        else:before,iterator=emitter.capture(self.model.iterators.construct(emitter,node,source,kind=site.source_type))
        pulled=self.model.iterators.pull(emitter,node,iterator);key=emitter.fresh()
        body=self._add(emitter,node,owner,Expression(key,pulled.kind),Expression(emitter.literal(1),'int',1),subtract=subtract)
        return before+'loop{let Some('+key+')=('+pulled.code+')else{break;};'+body+'}'

    def emit_constructor(self,emitter,node,arguments,keywords,wanted):
        from .native_classes import Expression
        site=self.sites[(emitter.plan.index,id(node))];record=wanted.record;record.emitted=True
        owner=emitter.fresh();value=Expression(owner,wanted);code='let '+owner+'='+self.mappings._new(emitter,record)+';'
        if arguments:code+=self._consume(emitter,node,value,arguments[0],site)
        if keywords:
            from .native import _string
            empty=emitter.fresh();code+='let '+empty+'='+owner+'.borrow().is_empty();'
            for key,amount in keywords:
                code+=self._add(emitter,node,value,Expression('NativeText::from('+_string(key)+')','str'),amount,replace_if_empty=empty)
        return Expression('{'+code+owner+'}',wanted)

    def show(self,emitter,value,node):
        from .native_classes import Expression,shape
        record=value.kind.record;owner,read,rows,left,right,key,item=(emitter.fresh()for _ in range(7))
        a=emitter.number(Expression(left+'.1.clone()',shape(record.value)))
        b=emitter.number(Expression(right+'.1.clone()',shape(record.value)))
        k=emitter.show(Expression(key+'.clone()',shape(record.key)),node,True)
        v=emitter.show(Expression(item+'.clone()',shape(record.value)),node,True)
        return '{let '+owner+'=('+value.code+').clone();let '+read+'='+owner+'.borrow();let mut '+rows+'='+read+'.entries.iter().collect::<Vec<_>>();'+rows+'.sort_by(|'+left+','+right+'|('+b+').cmp(&('+a+')));if '+rows+'.is_empty(){"Counter()".to_owned()}else{format!("Counter({{{}}})",'+rows+'.into_iter().map(|('+key+','+item+')|format!("{}: {}",'+k+','+v+')).collect::<Vec<_>>().join(", "))}}'


    def runtime(self):
        return COUNTER_HEAP if any(record.flavor=='Counter'for record in self.mappings.records)else''


COUNTER_HEAP=r'''
struct ClassCounterRank<K,V>{count:NativeInt,order:usize,key:K,value:V}
impl<K,V> PartialEq for ClassCounterRank<K,V>{fn eq(&self,other:&Self)->bool{self.count==other.count&&self.order==other.order}}
impl<K,V> Eq for ClassCounterRank<K,V>{}
impl<K,V> PartialOrd for ClassCounterRank<K,V>{fn partial_cmp(&self,other:&Self)->Option<std::cmp::Ordering>{Some(self.cmp(other))}}
impl<K,V> Ord for ClassCounterRank<K,V>{
    fn cmp(&self,other:&Self)->std::cmp::Ordering{other.count.cmp(&self.count).then_with(||self.order.cmp(&other.order))}
}
fn class_counter_best<K:Clone,V:Clone,F:Fn(&V)->NativeInt>(entries:&NativeDictionaryEntries<(K,V)>,count:usize,rank:F)->Result<Vec<(K,V)>,String>{
    if count==0{return Ok(Vec::new());}
    let mut heap=std::collections::BinaryHeap::<ClassCounterRank<K,V>>::new();
    heap.try_reserve(count).map_err(|_|"MemoryError: cannot allocate Counter selection".to_owned())?;
    for(order,(key,value))in entries.iter().enumerate(){
        let score=rank(value);
        if heap.len()<count{heap.push(ClassCounterRank{count:score,order,key:key.clone(),value:value.clone()});}
        else{
            let prior=heap.peek().unwrap();
            if score>prior.count||(score==prior.count&&order<prior.order){
                *heap.peek_mut().unwrap()=ClassCounterRank{count:score,order,key:key.clone(),value:value.clone()};
            }
        }
    }
    let mut selected=heap.into_vec();
    selected.sort_unstable_by(|left,right|right.count.cmp(&left.count).then_with(||left.order.cmp(&right.order)));
    let mut result=Vec::new();result.try_reserve(selected.len()).map_err(|_|"MemoryError: cannot allocate Counter result".to_owned())?;
    for item in selected{result.push((item.key,item.value));}Ok(result)
}
'''
