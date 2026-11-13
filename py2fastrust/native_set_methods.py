"""Canonical builtin set mutations with typed, sequential source consumption.

Actual builtin set sources use a callback-free contents operation. This does
not provide an arbitrary-order set iterator: observable traversal retains its
separate CPython-order capability boundary.
"""
import ast
from dataclasses import dataclass,field,replace

from .native_types import EMPTY,EmptyType,alternatives


def requires_frames(unit,analysis):
    from .native_constraints import Allocation
    from .native_key_types import SetType
    parents={id(child):node for node in ast.walk(unit.tree)for child in ast.iter_child_nodes(node)}
    for node in ast.walk(unit.tree):
        if not isinstance(node,ast.Call)or not isinstance(node.func,ast.Attribute)or node.func.attr not in {'update','clear'}:continue
        proved=any(isinstance(part,SetType)or isinstance(part,Allocation)and part.category=='set'
                   for facts in analysis.scopes.values()
                   for part in getattr(facts.values.get(unit.ordinal(node.func.value)),'alternatives',()))
        if not proved:
            proved=any(isinstance(kind,SetType)for facts in analysis.scopes.values()
                       for kind in alternatives(facts.expressions.get(unit.ordinal(node.func.value))))
        if proved and(node.func.attr=='update'or node.args or node.keywords
                      or not isinstance(node.func.value,ast.Name)or not isinstance(parents.get(id(node)),ast.Expr)):
            return True
    return False


@dataclass
class Site:
    receiver:object
    arguments:list
    keywords:object
    node:object=None
    cursors:dict=field(default_factory=dict)
    expanded:bool=False
    segments:list=field(default_factory=list)
    packed:object=None


class SetMethods:
    def __init__(self,mappings):
        self.mappings=mappings;self.model=mappings.model;self.sites={}

    def snapshot(self):
        from .native_classes import shape
        return tuple((key,shape(site.receiver),tuple(shape(value)for value in site.arguments),
                      shape(site.packed)if site.packed is not None else None)
                     for key,site in sorted(self.sites.items()))

    def default_empty(self):
        from .native_classes import Cell,merge
        for site in self.sites.values():
            if site.packed is not None and site.packed.root().tag is None:merge(site.packed,Cell(EMPTY),site.node)

    def receiver(self,node,value):
        from .native_classes import shape,ClassUnsupported
        from .native_class_mappings import mapping_kind
        if not isinstance(node.func,ast.Attribute)or node.func.attr not in {'update','clear'}:return False
        kinds=alternatives(shape(value))
        if not any(mapping_kind(kind)and kind.record.category=='set'for kind in kinds):return False
        if not all(mapping_kind(kind)and kind.record.flavor=='set'for kind in kinds):
            raise ClassUnsupported(node,'set mutation on mixed builtin-set and other receivers needs per-receiver method lookup before argument evaluation',types=(('receiver',shape(value)),),proof='canonical builtin set mutation receiver')
        return True

    def _key(self,records,value,node):
        from .native_classes import Cell,shape,ClassUnsupported
        from .native_class_mappings import key_supported,key_pending,unhashable_leaf
        from .native_types import TupleType
        from itertools import product
        kind=shape(value)
        if kind is None:return
        def variants(kind):
            choices=alternatives(kind)
            if len(choices)>1:return tuple(result for choice in choices for result in variants(choice))
            if key_pending(kind)and not self.model.final:return ()
            if isinstance(kind,TupleType):return tuple(replace(kind,fields=tuple(fields))for fields in product(*(variants(child)for child in kind.fields)))
            if unhashable_leaf(kind)is not None:return ()
            if key_supported(kind):return (kind,)
            raise ClassUnsupported(node,'set.update yielded a key whose custom, floating, or heterogeneous hash/equality protocol has no native adapter',types=(('key',kind),),proof='set update element hash/equality protocol')
        for choice in variants(kind):
            for record in records:self.mappings.contribute_key(record,Cell(choice),node)

    def _sources(self,plan,node,site,arguments,environment):
        from .native_classes import Cell,shape,ClassUnsupported
        from .native_class_mappings import mapping_kind
        records=[kind.record for kind in alternatives(shape(site.receiver))]
        for index,value in enumerate(arguments):
            kind=shape(value)
            choices=alternatives(kind)
            for choice_index,choice in enumerate(choices):
                if choice is None:
                    if self.model.final:raise ClassUnsupported(node,'set.update source has no solved iterable identity or element representation',proof='resolved set update iterable source')
                    continue
                if mapping_kind(choice)and choice.record.category=='set':
                    self._key(records,choice.record.key,node)
                elif isinstance(choice,EmptyType):continue
                else:
                    actual=value if len(choices)==1 else self.model.namespace.representation(choice,[value],node)
                    cursor=self.model.iterators.source(plan,node,actual,identity=('set_update',id(node),index,choice_index),environment=environment)
                    site.cursors[index,choice]=cursor
                    item=self.model.iterators.demand(plan,node,Cell(cursor),environment)
                    self._key(records,item,node)

    def analyze(self,plan,node,receiver,arguments,keywords,environment):
        if not self.receiver(node,receiver):return None
        site=Site(receiver,list(arguments),keywords,node=node)
        self.sites[plan.index,id(node)]=site
        if node.func.attr=='update'and not keywords:self._sources(plan,node,site,arguments,environment)
        return self.model.cell(plan,node,'none')

    def analyze_expanded(self,plan,node,receiver,environment):
        from .native_classes import Cell,shape,ClassUnsupported
        from .call_semantics import normalize_call,CallBindingError
        from .native_starred_calls import Segment
        if not isinstance(node.func,ast.Attribute)or node.func.attr not in {'update','clear'}:return None
        if not self.receiver(node,receiver):return None
        try:normalized=normalize_call(node,allow_starred=True)
        except CallBindingError as error:raise ClassUnsupported(node,str(error),proof='set mutation keyword mapping expansion')from None
        key=plan.index,id(node)
        old=self.sites.get(key)
        packed=old.packed if old is not None and old.expanded else Cell()
        site=Site(receiver,[],{},node=node,expanded=True,packed=packed)
        deferred=None
        def analyze_spread(segment):
            value=segment.value;original=segment.node
            if getattr(shape(value),'_native_class_generator',False):segment.element=self.model.generators.demand(plan,node,value,environment)
            else:
                segment.iterator=self.model.iterators.source(plan,original,value,identity=('set_call_expand',id(node),id(original)),environment=environment)
                segment.element=self.model.iterators.demand(plan,node,Cell(segment.iterator),environment)
            self.model.expanded_calls._contribute(packed,segment.element,original)
        for original,arg in zip(node.args,normalized.positional):
            value=self.model.expression(plan,arg.expression,environment)
            segment=Segment(original,arg.spread,value)
            if arg.spread:
                if len(node.args)==1:deferred=segment
                else:analyze_spread(segment)
            else:self.model.expanded_calls._contribute(packed,value,original)
            site.segments.append(segment)
        site.keywords={arg.name:self.model.expression(plan,arg.expression,environment)for arg in normalized.keywords}
        if deferred is not None:analyze_spread(deferred)
        site.arguments=[packed]
        if shape(packed)is None and self.model.final:
            from .native_classes import merge
            merge(packed,Cell(EMPTY),node)
        self.sites[key]=site
        if node.func.attr=='update'and not site.keywords:self._sources(plan,node,site,[packed],environment)
        return self.model.cell(plan,node,'none')

    def _insert(self,emitter,node,owner,item):
        from .native_classes import Expression
        from .native_unions import project,union_kind
        from .native_class_mappings import unhashable_leaf,query_type_name
        from .native_types import TupleType,tuple_code
        from .native import _string
        def inspect(key,finish,outer=None):
            kind,code=key.kind,key.code
            if union_kind(kind):return project(kind,code,lambda child,text:'{'+inspect(Expression('('+text+').clone()',child),finish,outer)+'}')+';'
            if outer is None:outer=key
            if isinstance(kind,EmptyType):return 'native_empty::<()>('+code+');'
            if isinstance(kind,TupleType):
                def field(index,values):
                    if index==len(kind.fields):return finish(Expression(tuple_code(value.code for value in values),replace(kind,fields=tuple(value.kind for value in values))))
                    child=Expression('('+code+').'+str(index)+'.clone()',kind.fields[index])
                    return inspect(child,lambda captured:field(index+1,values+[captured]),outer)
                return field(0,[])
            leaf=unhashable_leaf(kind)
            if leaf is not None:
                error='format!("TypeError: cannot use \'{}\' as a set element (unhashable type: \'{}\')",'+query_type_name(emitter,outer,node)+','+_string(leaf)+')'
                return emitter.at('Err::<(),String>('+error+')',node)+';'
            return finish(key)
        return inspect(item,lambda key:self.mappings._set(emitter,node,owner,key,Expression('()','none')))

    def _consume(self,emitter,node,site,index,owner,source):
        from .native_classes import Expression,shape
        from .native_class_mappings import mapping_kind
        from .native_unions import project
        def branch(kind,code):
            value=Expression('('+code+').clone()',kind)
            if isinstance(kind,EmptyType):return 'native_empty::<()>('+code+');'
            if mapping_kind(kind)and kind.record.category=='set':
                # All admitted key types are immutable builtin values. Hashing,
                # equality and copying cannot run Python callbacks or expose
                # the source's internal traversal. Aliases are an exact no-op.
                other,loan,key=(emitter.fresh()for _ in range(3))
                body='let '+other+'='+value.code+';'
                insert=self._insert(emitter,node,owner,Expression(key+'.clone()',shape(kind.record.key)))
                loop='let '+loan+'='+other+'.borrow();for ('+key+',_)in '+loan+'.entries.iter(){'+insert+'}'
                if shape(kind.record.key)==shape(owner.kind.record.key):
                    body+='if !Rc::ptr_eq(&'+owner.code+ ',&'+other+'){'+loop+'}'
                else:body+=loop
                return body
            cursor=site.cursors[index,kind]
            before,iterator=emitter.capture(self.model.iterators.construct(emitter,node,value,kind=cursor))
            pulled=self.model.iterators.pull(emitter,node,iterator);item=emitter.fresh()
            return before+'loop{let Some('+item+')=('+pulled.code+')else{break;};'+self._insert(emitter,node,owner,Expression(item,pulled.kind))+'}'
        return project(source.kind,source.code,lambda kind,code:'{'+branch(kind,code)+'}')+';'

    def _finish(self,emitter,node,site,owner,arguments,count):
        from .native_classes import Expression
        from .native_unions import project
        from .native import _string
        name=node.func.attr
        if site.keywords:return emitter.at('Err::<(),String>('+_string('TypeError: set.'+name+'() takes no keyword arguments')+'.to_owned())',node)
        if name=='clear':
            error=emitter.at('Err::<(),String>(format!("TypeError: set.clear() takes no arguments ({} given)",'+count+'))',node)
            cleared=project(owner.kind,owner.code,lambda kind,code:'{('+code+').borrow_mut().clear();()}')
            return 'if '+count+'!=0{'+error+'}else{'+cleared+'}'
        def mutate(kind,code):
            destination=Expression('('+code+').clone()',kind)
            if site.expanded:
                item=emitter.fresh();vector=arguments[0]
                return '{for '+item+' in '+vector.code+'{'+self._consume(emitter,node,site,0,destination,Expression(item,vector.kind))+'}()}'
            return '{'+''.join(self._consume(emitter,node,site,index,destination,arg)for index,arg in enumerate(arguments))+'()}'
        return project(owner.kind,owner.code,mutate)

    def emit(self,emitter,node,*,expanded=False):
        from .native_classes import Expression,shape
        from .call_semantics import normalize_call
        site=self.sites.get((emitter.plan.index,id(node)))
        if site is None or site.expanded!=expanded:return None
        before,owner=emitter.capture(emitter.expression(node.func.value));arguments=[]
        if not expanded:
            for arg in normalize_call(node).evaluation_order:
                more,value=emitter.capture(emitter.expression(arg.expression));before+=more
                if arg.name is None:arguments.append(value)
            count=str(len(arguments))+'usize'
        else:
            element=shape(site.packed);vector=emitter.fresh()
            before+='let mut '+vector+':Vec<'+emitter.rust_type(element)+'>=Vec::new();'
            deferred=None
            for segment in site.segments:
                arg=segment.node.value if segment.spread else segment.node
                more,value=emitter.capture(emitter.expression(arg));before+=more
                if segment.spread:
                    if len(node.args)==1:deferred=segment,value
                    else:before+=self._expand(emitter,node,segment,value,vector,element)
                else:before+=vector+'.push('+emitter.coerce(value,element,node)+');'
            for kw in node.keywords:
                more,_=emitter.capture(emitter.expression(kw.value));before+=more
            if deferred is not None:before+=self._expand(emitter,node,*deferred,vector,element)
            count=emitter.fresh();before+='let '+count+'='+vector+'.len();'
            arguments=[Expression(vector,element)]
        return Expression('{'+before+self._finish(emitter,node,site,owner,arguments,count)+'}','none')

    def _expand(self,emitter,node,segment,value,vector,element):
        from .native_classes import Expression
        from .native_class_builtins import _type_name
        def append(e,item):
            return e.at(vector+'.try_reserve(1).map_err(|_|"MemoryError: cannot expand set method arguments".to_owned())',node)+';'+vector+'.push('+e.coerce(item,element,node)+');'
        if getattr(value.kind,'_native_class_generator',False):
            return self.model.generators.consume(emitter,node,'set_call_expansion',value,[],{},'none',append_item=append).code+';'
        label='set.'+node.func.attr+'() argument'if len(node.args)==1 else'Value'
        callback=lambda current:'format!("TypeError: '+label+' after * must be an iterable, not {}",'+_type_name(emitter,current,node)+')'
        before,iterator=emitter.capture(self.model.iterators.construct(emitter,node,value,kind=segment.iterator,not_iterable=callback))
        pulled=self.model.iterators.pull(emitter,node,iterator);item=emitter.fresh()
        return before+'loop{let Some('+item+')=('+pulled.code+')else{break;};'+append(emitter,Expression(item,pulled.kind))+'}'
