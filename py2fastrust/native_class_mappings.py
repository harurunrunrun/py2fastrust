"""Registered typed mapping handles over the shared native hash-key storage."""
import ast
from dataclasses import dataclass,field

from .native_types import EMPTY,EmptyType,TupleType,TupleSequenceType,alternatives


@dataclass(frozen=True)
class MappingType:
    index:int
    record:object=field(compare=False,hash=False,repr=False)
    _native_reference_cloneable=True
    _native_class_mapping=True

    @property
    def _native_kind_tag(self):return 'class_mapping_'+str(self.index)

    @property
    def _native_owned_kinds(self):
        from .native_classes import shape
        return (shape(self.record.key),shape(self.record.value),*((shape(self.record.default_factory),)if self.record.default_factory is not None else()))


@dataclass
class MappingRecord:
    index:int
    category:str
    node:object
    plan:object
    key:object
    value:object
    operation:str='literal'
    source:object=None
    source_type:object=None
    emitted:bool=False
    flavor:str='dict'
    default_factory:object=None

    @property
    def kind(self):return MappingType(self.index,self)


def mapping_kind(kind):return isinstance(kind,MappingType)


def key_supported(kind):
    return (isinstance(kind,EmptyType)or kind in {'int','bool','int_bool','str','bytes','none'}
        or isinstance(kind,TupleType)and all(key_supported(child)for child in kind.fields)
        or isinstance(kind,TupleSequenceType)and key_supported(kind.element))


def key_pending(kind):
    if kind is None:return True
    if isinstance(kind,TupleType):return any(key_pending(child)for child in kind.fields)
    if isinstance(kind,TupleSequenceType):return key_pending(kind.element)
    choices=alternatives(kind)
    return len(choices)>1 and any(key_pending(child)for child in choices)


def key_compatible(left,right):
    if isinstance(left,EmptyType)or isinstance(right,EmptyType):return False
    if left in {'int','bool','int_bool'}and right in {'int','bool','int_bool'}:return True
    if left==right and left in {'str','bytes','none'}:return True
    if isinstance(left,TupleType)and isinstance(right,TupleType):
        return len(left.fields)==len(right.fields)and all(key_compatible(a,b)for a,b in zip(left.fields,right.fields))
    if isinstance(left,TupleSequenceType)and isinstance(right,TupleSequenceType):return key_compatible(left.element,right.element)
    return False


def canonical_type(kind):
    from .native_key_types import canonical_tuple
    if isinstance(kind,EmptyType):return 'NativeEmpty'
    if kind in {'int','bool','int_bool'}:return 'NativeInt'
    if kind=='str':return 'NativeText'
    if kind=='bytes':return 'Vec<u8>'
    if kind=='none':return '()'
    if isinstance(kind,TupleType):return canonical_tuple(canonical_type(child)for child in kind.fields)
    if isinstance(kind,TupleSequenceType):return 'Vec<'+canonical_type(kind.element)+'>'
    raise KeyError(kind)


def canonical(emitter,value):
    from .native_classes import Expression
    from .native_key_types import canonical_tuple
    kind,code=value.kind,value.code
    if isinstance(kind,EmptyType):return 'match '+code+'{}'
    if kind in {'int','bool','int_bool'}:return emitter.number(Expression('('+code+').clone()',kind))
    if kind in {'str','bytes'}:return '('+code+').clone()'
    if kind=='none':return '()'
    if isinstance(kind,TupleType):
        return canonical_tuple(canonical(emitter,Expression(f'({code}).{index}.clone()',child))for index,child in enumerate(kind.fields))
    if isinstance(kind,TupleSequenceType):
        item=emitter.fresh()
        return '('+code+').iter().map(|'+item+'|'+canonical(emitter,Expression(item+'.clone()',kind.element))+').collect::<Vec<_>>()'
    raise KeyError(kind)


def copy_query(emitter,kind):
    from .native_classes import Expression
    key=emitter.fresh()
    return '|'+key+'|'+canonical(emitter,Expression('(*'+key+').clone()',kind))


def query_canonical(emitter,value,wanted):
    """Hash equivalent immutable tuple layouts using the stored key ABI."""
    from .native_classes import Expression
    from .native_key_types import canonical_tuple
    actual=value.kind;result_type=canonical_type(wanted)
    absent='None::<'+result_type+'>'
    if isinstance(actual,EmptyType)or isinstance(wanted,EmptyType):return absent
    if not isinstance(actual,(TupleType,TupleSequenceType))and not isinstance(wanted,(TupleType,TupleSequenceType)):
        return 'Some('+canonical(emitter,value)+')'if key_compatible(actual,wanted)else absent
    if isinstance(wanted,TupleType):
        if isinstance(actual,TupleType):
            if len(actual.fields)!=len(wanted.fields):return absent
            children=[Expression('('+value.code+').'+str(index)+'.clone()',kind)for index,kind in enumerate(actual.fields)]
            guard=''
        elif isinstance(actual,TupleSequenceType):
            children=[Expression('('+value.code+').as_slice()['+str(index)+'].clone()',actual.element)for index in range(len(wanted.fields))]
            guard='if ('+value.code+').len()!='+str(len(wanted.fields))+'{return None;}'
        else:return absent
        captures=[];fields=[]
        for child,target in zip(children,wanted.fields):
            name=emitter.fresh();captures.append('let '+name+'=('+query_canonical(emitter,child,target)+')?;');fields.append(name)
        return '(||->Option<'+result_type+'>{'+guard+''.join(captures)+'Some('+canonical_tuple(fields)+')})()'
    if isinstance(wanted,TupleSequenceType):
        if isinstance(actual,TupleType):
            captures=[];fields=[]
            for index,kind in enumerate(actual.fields):
                child=Expression('('+value.code+').'+str(index)+'.clone()',kind);name=emitter.fresh()
                captures.append('let '+name+'=('+query_canonical(emitter,child,wanted.element)+')?;');fields.append(name)
            return '(||->Option<'+result_type+'>{'+''.join(captures)+'Some(vec!['+','.join(fields)+'])})()'
        if isinstance(actual,TupleSequenceType):
            item,values=(emitter.fresh()for _ in range(2))
            converted=query_canonical(emitter,Expression(item+'.clone()',actual.element),wanted.element)
            return '(||->Option<'+result_type+'>{let mut '+values+'=Vec::new();for '+item+' in ('+value.code+').iter(){'+values+'.push(('+converted+')?);}Some('+values+')})()'
    return absent


def unhashable_leaf(kind):
    from .native_types import ListType
    if isinstance(kind,ListType):return 'list'
    if mapping_kind(kind):return kind.record.flavor
    if isinstance(kind,TupleType):
        for child in kind.fields:
            result=unhashable_leaf(child)
            if result is not None:return result
    return None


def query_type_name(emitter,value,node):
    from .native_class_builtins import _type_name
    if mapping_kind(value.kind)and value.kind.record.flavor in {'Counter','defaultdict'}:return '"collections.'+value.kind.record.flavor+'"'
    return _type_name(emitter,value,node)


class Mappings:
    def __init__(self,model):
        self.model=model;self.records=[];self.sites={};self.methods={};self.augmented={}
        from .native_mapping_views import Views
        self.views=Views(self)
        from .native_class_counters import Counters
        self.counters=Counters(self)
        from .native_class_defaultdicts import DefaultDicts
        self.defaultdicts=DefaultDicts(self)
        from .native_set_methods import SetMethods
        self.set_methods=SetMethods(self)
        from .native_cpython_set_adapters import CPythonSets
        self.cpython_sets=CPythonSets(self)

    def owns(self,kind):
        return mapping_kind(kind)and 0<=kind.index<len(self.records)and self.records[kind.index]is kind.record

    def record(self,plan,node,category,operation='literal',flavor=None):
        from .native_classes import Cell
        flavor=flavor or category
        key=plan.index,id(node),category,flavor
        if key not in self.sites:
            self.sites[key]=MappingRecord(len(self.records),category,node,plan,Cell(),Cell('none')if category=='set'else Cell(),operation)
            self.sites[key].flavor=flavor
            self.records.append(self.sites[key])
        return self.sites[key]

    def snapshot(self):
        from .native_classes import shape
        return tuple((r.category,r.flavor,shape(r.key),shape(r.value),shape(r.default_factory)if r.default_factory is not None else None)for r in self.records),self.views.snapshot(),self.set_methods.snapshot()

    def default_uninhabited(self):
        from .native_classes import Cell,merge
        self.set_methods.default_empty()
        for record in self.records:
            for value in (record.key,record.value):
                if value is record.value and record.flavor=='defaultdict'and self.defaultdicts.pending_value(record):continue
                if value.root().tag is None:merge(value,Cell(EMPTY),record.node)

    def validate(self,kind,node,seen):
        from .native_classes import ClassUnsupported
        from .native_class_storage import validate
        if not self.owns(kind):raise ClassUnsupported(node,'this dictionary/set handle has no registered allocation family',proof='registered mapping storage ownership')
        marker=('mapping',kind.index)
        if marker in seen:raise ClassUnsupported(node,'these dictionary/set payloads form a recursive ownership layout; cycle-aware typed mapping storage is not implemented',proof='finite mapping layout and cycle-aware lifetime')
        record=kind.record
        validate(record.key,node,self.model.integer,seen=seen|{marker},model=self.model)
        validate(record.value,node,self.model.integer,seen=seen|{marker},model=self.model)
        if record.default_factory is not None:validate(record.default_factory,node,self.model.integer,seen=seen|{marker},model=self.model)
        from .native_classes import shape
        if not key_supported(shape(record.key)):
            raise ClassUnsupported(node,'this dictionary/set key family needs a heterogeneous or custom Python hash/equality protocol not implemented by the typed native hash adapter',types=(('key',shape(record.key)),),proof='compatible native hash-key representation')
        self.counters.validate(record,node)

    def add_lifetime_edges(self,edges,targets):
        for record in self.records:
            edges[('mapping',record.index)]={target for child in record.kind._native_owned_kinds if child is not None for target in targets(child)}
        self.views.add_lifetime_edges(edges,targets)

    def contribute_key(self,record,value,node):
        from .native_classes import shape,ClassUnsupported
        kind=shape(value)
        if kind is None:return
        if not key_supported(kind)and not(not self.model.final and key_pending(kind)):
            raise ClassUnsupported(node,'this dictionary/set key requires a custom or unhashable key protocol that has no native representation yet',types=(('key',kind),),proof='native hash-key protocol')
        self.model.contribute(record.key,value,node)

    def analyze_expression(self,plan,node,environment):
        from .native_classes import Cell
        if isinstance(node,(ast.Dict,ast.Set)):
            record=self.record(plan,node,'dict'if isinstance(node,ast.Dict)else'set')
            if isinstance(node,ast.Dict):
                if any(key is None for key in node.keys):
                    from .native_classes import ClassUnsupported
                    raise ClassUnsupported(node,'dictionary ** expansion needs mapping key iteration and overwrite dispatch not yet represented',proof='dictionary mapping expansion')
                for key,value in zip(node.keys,node.values):
                    captured=self.model.expression(plan,key,environment)
                    result=self.model.expression(plan,value,environment)
                    self.contribute_key(record,captured,key);self.model.contribute(record.value,result,value)
            else:
                for key in node.elts:self.contribute_key(record,self.model.expression(plan,key,environment),key)
            return self.model.cell(plan,node,record.kind)
        if isinstance(node,(ast.DictComp,ast.SetComp)):
            record=self.record(plan,node,'dict'if isinstance(node,ast.DictComp)else'set','comprehension')
            from .native_class_comprehensions import analyze
            def contribute(inside,semantic):
                if record.category=='dict':
                    key,value=semantic.elements
                    captured=self.model.expression(plan,key,inside)
                    result=self.model.expression(plan,value,inside)
                    self.contribute_key(record,captured,key);self.model.contribute(record.value,result,value)
                else:self.contribute_key(record,self.model.expression(plan,semantic.element,inside),semantic.element)
                return self.model.cell(plan,node,record.kind)
            return analyze(self.model,plan,node,environment,contribute=contribute)
        return None

    def analyze_builtin(self,plan,node,name,arguments,keywords,environment,factory):
        from .native_classes import Cell,ClassUnsupported,shape
        if name not in {'dict','set'}:return None
        if len(arguments)>1 or name=='set'and keywords:
            raise ClassUnsupported(node,'this mapping constructor needs a compatible captured argument binding',proof='mapping constructor signature')
        record=self.record(plan,node,name,'constructor')
        if arguments:
            source=arguments[0];kind=shape(source);record.source=source
            choices=alternatives(kind)
            if choices and all(mapping_kind(choice)for choice in choices):
                for choice in choices:
                    if name=='dict'and choice.record.category!='dict':raise ClassUnsupported(node)
                    self.contribute_key(record,choice.record.key,node)
                    if name=='dict':self.model.contribute(record.value,choice.record.value,node)
            else:
                record.source_type=self.model.iterators.source(plan,node,source,environment=environment)
                item=self.model.iterators.demand(plan,node,Cell(record.source_type),environment)
                if name=='set':self.contribute_key(record,item,node)
                elif item.root().tag=='tuple'and len(item.root().args)==2:
                    self.contribute_key(record,item.root().args[0],node)
                    self.model.contribute(record.value,item.root().args[1],node)
                elif shape(item)is not None:
                    raise ClassUnsupported(node,'dict(iterable) currently needs typed two-element update pairs; generic per-element unpacking/error protocols remain unimplemented',types=(('element',shape(item)),),proof='dictionary update pair protocol')
        for key,value in keywords:
            self.contribute_key(record,Cell('str'),node);self.model.contribute(record.value,value,node)
        return factory(record.kind)

    def analyze_item(self,plan,node,owner,index,environment):
        from .native_classes import shape,ClassUnsupported
        kinds=alternatives(shape(owner))
        if not any(mapping_kind(kind)for kind in kinds):return None
        result=self.model.cell(plan,node)
        for kind in kinds:
            if not mapping_kind(kind)or kind.record.category!='dict':
                raise ClassUnsupported(node,'this mixed mapping receiver needs per-alternative subscript dispatch beyond dictionary handles',proof='mapping subscript receiver alternatives')
            self.defaultdicts.analyze_get(plan,node,kind.record,index,environment)
            self.model.contribute(result,kind.record.value,node)
        return self.model.remember(plan,node,result)

    def analyze_store(self,plan,node,owner,index,value,environment):
        from .native_classes import shape,ClassUnsupported
        kinds=alternatives(shape(owner))
        if not any(mapping_kind(kind)for kind in kinds):return False
        for kind in kinds:
            if not mapping_kind(kind)or kind.record.category!='dict':raise ClassUnsupported(node)
            self.contribute_key(kind.record,index,node);self.model.contribute(kind.record.value,value,node)
        self.model.remember(plan,node,value)
        return True

    def analyze_method(self,plan,node,receiver,arguments,keywords,environment):
        from .native_classes import shape,Cell,ClassUnsupported
        # A point receiver can change adapters on a later analysis visit.
        getattr(self.model,'mapping_update_calls',{}).pop((plan.index,id(node),None),None)
        getattr(self.model,'mapping_pop_calls',{}).pop((plan.index,id(node),None),None)
        mutated=self.set_methods.analyze(plan,node,receiver,arguments,keywords,environment)
        if mutated is not None:return mutated
        counted=self.counters.analyze_method(plan,node,receiver,arguments,keywords,environment)
        if counted is not None:return counted
        view=self.views.analyze(plan,node,receiver,arguments,keywords)
        if view is not None:
            self.methods[(plan.index,id(node))]=(receiver,node.func.attr)
            return view
        from .native_mapping_update import analyze as analyze_update
        updated=analyze_update(self.model,plan,node,receiver,arguments,keywords,environment)
        if updated is not None:return updated
        from .native_mapping_pop import analyze as analyze_pop
        popped_key=analyze_pop(self.model,plan,node,receiver,arguments,keywords)
        if popped_key is not None:return popped_key
        from .native_mapping_popitem import analyze as analyze_popitem
        popped=analyze_popitem(self.model,plan,node,receiver,arguments,keywords)
        if popped is not None:return popped
        kinds=alternatives(shape(receiver))
        if not any(mapping_kind(kind)for kind in kinds):return None
        name=node.func.attr
        if keywords:raise ClassUnsupported(node,'mapping method keyword argument binding is not implemented for this signature',proof='mapping method argument binding')
        result=self.model.cell(plan,node)
        self.methods[(plan.index,id(node))]=(receiver,name)
        if name=='clear'and not arguments and all(mapping_kind(kind)and kind.record.category=='dict'for kind in kinds):
            return self.model.cell(plan,node,'none')
        if name=='copy'and not arguments:
            if len(kinds)!=1:raise ClassUnsupported(node,'copying these mapping alternatives needs a joined destination key/value ABI',proof='mapping copy result representation')
            old=kinds[0].record;record=self.record(plan,node,old.category,'copy',flavor=old.flavor);record.source=receiver
            self.defaultdicts.copy_record(record,old,node)
            self.contribute_key(record,old.key,node);self.model.contribute(record.value,old.value,node)
            return self.model.cell(plan,node,record.kind)
        if name in {'get','setdefault'}and 1<=len(arguments)<=2:
            for kind in kinds:
                if not mapping_kind(kind)or kind.record.category!='dict':raise ClassUnsupported(node)
                default=arguments[1]if len(arguments)==2 else Cell('none')
                if name=='setdefault':
                    self.contribute_key(kind.record,arguments[0],node)
                    self.model.contribute(kind.record.value,default,node)
                self.model.contribute(result,kind.record.value,node)
                self.model.contribute(result,default,node)
            return result
        if name=='add'and len(arguments)==1:
            for kind in kinds:
                if not mapping_kind(kind)or kind.record.category!='set':raise ClassUnsupported(node)
                self.contribute_key(kind.record,arguments[0],node)
            return self.model.cell(plan,node,'none')
        if name in {'remove','discard'}and len(arguments)==1:
            for kind in kinds:
                if not mapping_kind(kind)or kind.record.category!='set':raise ClassUnsupported(node)
            argument=shape(arguments[0])
            if argument is not None and not key_supported(argument)and not(not self.model.final and key_pending(argument)):
                raise ClassUnsupported(node,'set deletion with this argument needs a Python hash/equality adapter that is not implemented',types=(('key',argument),),proof='set deletion query key')
            return self.model.cell(plan,node,'none')
        if name=='pop'and not arguments:
            for kind in kinds:
                if not mapping_kind(kind)or kind.record.category!='set':raise ClassUnsupported(node)
                self.model.contribute(result,kind.record.key,node)
            return result
        raise ClassUnsupported(node,'mapping method '+repr(name)+' needs a native view/mutation/argument protocol not implemented by this adapter',proof='mapping method protocol')

    def rust_type(self,kind):return 'ClassMapping_'+str(kind.index)

    def _new(self,emitter,record):
        from .native_classes import shape
        if record.category=='set':return self.cpython_sets.new(emitter,record)
        key,value=shape(record.key),shape(record.value)
        result='Rc::new(RefCell::new(NativeKeyDict::<'+emitter.rust_type(key)+','+emitter.rust_type(value)+','+canonical_type(key)+'>::new()))'
        if record.category=='dict'and self.views.positions_enabled()and isinstance(record.node,ast.Dict):
            from .native_dictionary_positions import literal_presize
            count=literal_presize(record.node)
            if count<=5:return result
            owner=emitter.fresh()
            result='{let '+owner+'='+result+';'+emitter.at(owner+'.borrow_mut().presize_literal('+str(count)+')',record.node)+';'+owner+'}'
        return result

    def _set(self,emitter,node,owner,key,value):
        from .native_classes import shape,Expression
        if owner.kind.record.category=='set':return self.cpython_sets.insert(emitter,node,owner,key)
        record=owner.kind.record;wanted=shape(record.key)
        retained=emitter.coerce(Expression('('+key.code+').clone()',key.kind),wanted,node)
        stored=emitter.coerce(Expression('('+value.code+').clone()',value.kind),shape(record.value),node)
        key_name,canonical_name=(emitter.fresh()for _ in range(2))
        return f'let {key_name}:{emitter.rust_type(wanted)}={retained};let {canonical_name}={canonical(emitter,Expression(key_name,wanted))};'+emitter.at(f'{owner.code}.borrow_mut().set({key_name},{canonical_name},{stored})',node)+';'

    def emit_expression(self,emitter,node):
        from .native_classes import Expression
        wanted=emitter.kind(node)
        if not mapping_kind(wanted):return None
        record=wanted.record;record.emitted=True
        if isinstance(node,ast.Set):return self.cpython_sets.literal(emitter,node,wanted)
        if isinstance(node,(ast.DictComp,ast.SetComp)):
            from .native_class_comprehensions import Collector,emit
            def append(e,result,semantic):
                if record.category=='dict':
                    key_node,value_node=semantic.elements
                    before,key=e.capture(e.expression(key_node));more,value=e.capture(e.expression(value_node))
                else:
                    before,key=e.capture(e.expression(semantic.element));more='';value=Expression('()','none')
                return before+more+self._set(e,node,Expression(result,wanted),key,value)
            collector=Collector(lambda e,result,kind:f'let {result}={self._new(e,record)};',append,lambda e,result,kind:result)
            return emit(emitter,node,collector=collector)
        owner=emitter.fresh();code=f'let {owner}={self._new(emitter,record)};'
        pairs=zip(node.keys,node.values)if isinstance(node,ast.Dict)else((key,None)for key in node.elts)
        for key_node,value_node in pairs:
            before,key=emitter.capture(emitter.expression(key_node));code+=before
            if value_node is None:value=Expression('()','none')
            else:
                before,value=emitter.capture(emitter.expression(value_node));code+=before
            code+=self._set(emitter,node,Expression(owner,wanted),key,value)
        return Expression('{'+code+owner+'}',wanted)

    def emit_builtin(self,emitter,node,name,arguments,keywords,wanted):
        from .native_classes import Expression,shape,ClassUnsupported
        record=wanted.record;record.emitted=True;owner=emitter.fresh();code=f'let {owner}={self._new(emitter,record)};'
        if arguments:
            source=arguments[0]
            choices=alternatives(source.kind)
            if choices and all(mapping_kind(choice)for choice in choices):
                from .native_unions import project,union_kind
                def copy(kind,text):
                    if name=='set':return self.cpython_sets.from_mapping(emitter,node,Expression(owner,wanted),Expression(text,kind))
                    stable,key,value,read=(emitter.fresh()for _ in range(4));old=kind.record
                    body=f'{{let {stable}=({text}).clone();let {read}={stable}.borrow();for ({key},{value})in {read}.entries.iter(){{'
                    if name=='dict'and self.views.positions_enabled():
                        body=f'{{let {stable}=({text}).clone();let {read}={stable}.borrow();'+emitter.at(owner+'.borrow_mut().prepare_mapping_seed(&'+read+'.entries)',node)+f';for ({key},{value})in {read}.entries.iter(){{'
                    return body+self._set(emitter,node,Expression(owner,wanted),Expression(key+'.clone()',shape(old.key)),Expression(value+'.clone()',shape(old.value))if name=='dict'else Expression('()','none'))+'}}'
                code+=(project(source.kind,source.code,copy)if union_kind(source.kind)else copy(source.kind,source.code))+';'
            else:
                setup,iterator=emitter.capture(self.model.iterators.construct(emitter,node,source,kind=record.source_type));code+=setup
                pulled=self.model.iterators.pull(emitter,node,iterator);item=emitter.fresh()
                code+=f'loop{{let Some({item})=({pulled.code})else{{break;}};'
                if name=='set':key=Expression(item,pulled.kind);value=Expression('()','none')
                else:key=Expression(item+'.0',pulled.kind.fields[0]);value=Expression(item+'.1',pulled.kind.fields[1])
                code+=self._set(emitter,node,Expression(owner,wanted),key,value)+'}'
        from .native import _string
        if name=='dict'and keywords and self.views.positions_enabled():
            code+=emitter.at(owner+'.borrow_mut().prepare_keywords('+str(len(keywords))+')',node)+';'
        for key,value in keywords.items():code+=self._set(emitter,node,Expression(owner,wanted),Expression('NativeText::from('+_string(key)+')','str'),value)
        return Expression('{'+code+owner+'}',wanted)

    def emit_get(self,emitter,node,owner,key,wanted,default=None):
        from .native_classes import Expression,shape,ClassUnsupported
        from .native_unions import project,union_kind
        from .native_class_builtins import _error
        if union_kind(owner.kind):
            return Expression(project(owner.kind,owner.code,lambda kind,code:self.emit_get(emitter,node,Expression('('+code+').clone()',kind),key,wanted,default).code),wanted)
        record=owner.kind.record;source_kind=shape(record.key)
        if not key_supported(key.kind):
            from .native_class_builtins import _type_name
            from .native import _string
            leaf=unhashable_leaf(key.kind)
            if leaf is None:raise ClassUnsupported(node,'this dictionary query needs a floating/custom hash and equality adapter that has not been implemented; it cannot be treated as an unhashable value or as a missing key',types=(('key',key.kind),),proof='Python query-key hash/equality protocol')
            return _error(emitter,node,wanted,'format!("TypeError: cannot use \'{}\' as a dict key (unhashable type: \'{}\')",'+query_type_name(emitter,key,node)+','+_string(leaf)+')')
        if default is None:
            if record.flavor=='defaultdict':absent=self.defaultdicts.missing(emitter,node,owner,key,wanted)
            elif record.flavor=='Counter':absent=emitter.coerce(Expression(emitter.literal(0),'int',0),wanted,node)
            else:
                from .native_integer_digit_limits import guard_error_repr
                guard_error_repr(emitter,key,node)
                error='format!("KeyError: {}",'+emitter.show(key,node,True)+')'
                absent=emitter.at(f'Err::<{emitter.rust_type(wanted)},String>({error})',node)
        else:absent=emitter.coerce(default,wanted,node)
        value,found,canonical_name=(emitter.fresh()for _ in range(3))
        query=query_canonical(emitter,key,source_kind)
        lookup=f'{{let {found}=match {query}{{Some({canonical_name})=>{owner.code}.borrow().get(&{canonical_name}).cloned(),None=>None}};{found}}}'
        present=emitter.coerce(Expression(value,shape(record.value)),wanted,node)
        return Expression(f'match {lookup}{{Some({value})=>{present},None=>{absent}}}',wanted)

    def emit_store(self,emitter,node,owner,key,value):
        from .native_classes import Expression
        from .native_unions import project,union_kind
        if union_kind(owner.kind):return project(owner.kind,owner.code,lambda kind,code:'{'+self.emit_store(emitter,node,Expression('('+code+').clone()',kind),key,value)+'}')+';'
        return self._set(emitter,node,owner,key,value)

    def emit_method(self,emitter,node):
        from .native_mapping_pop import emit as emit_pop
        popped_key=emit_pop(emitter,node)
        if popped_key is not None:return popped_key
        from .native_mapping_update import emit as emit_update
        updated=emit_update(emitter,node)
        if updated is not None:return updated
        from .native_mapping_popitem import emit as emit_popitem
        popped=emit_popitem(emitter,node)
        if popped is not None:return popped
        mutated=self.set_methods.emit(emitter,node)
        if mutated is not None:return mutated
        counted=self.counters.emit_method(emitter,node)
        if counted is not None:return counted
        from .native_classes import Expression,shape
        from .call_semantics import normalize_call
        if (emitter.plan.index,id(node))not in self.methods:return None
        setup,owner=emitter.capture(emitter.expression(node.func.value));arguments=[]
        for argument in normalize_call(node).evaluation_order:
            before,value=emitter.capture(emitter.expression(argument.expression));setup+=before;arguments.append(value)
        wanted=emitter.kind(node);name=node.func.attr
        if getattr(wanted,'_native_mapping_view',False):code=self.views.emit(emitter,node,owner,wanted)
        elif name=='copy':
            record=wanted.record;record.emitted=True
            if record.category=='set':
                copied=emitter.fresh();code='{let '+copied+'='+self._new(emitter,record)+';'+self.cpython_sets.merge(emitter,node,Expression(copied,wanted),owner)+copied+'}'
            elif record.flavor=='defaultdict':code=self.defaultdicts.emit_copy(emitter,node,owner,wanted)
            else:
                from .native_classes import shape
                method='try_constructor_copy'if record.flavor=='Counter'else'try_python_copy'
                query=copy_query(emitter,shape(owner.kind.record.key))
                copied=emitter.fresh()
                call=emitter.at(owner.code+'.borrow().'+method+'('+query+')',node)
                code='{let '+copied+'='+call+';Rc::new(RefCell::new('+copied+'))}'
        elif name=='add':code='{'+self.emit_store(emitter,node,owner,arguments[0],Expression('()','none'))+'()}'
        elif name=='clear':
            from .native_unions import project
            code=project(owner.kind,owner.code,lambda kind,text:'{('+text+').borrow_mut().clear();()}')
        elif name in {'remove','discard'}:
            from .native_unions import union_kind,project
            key=arguments[0]
            def branch(kind,text):
                canonical_name=emitter.fresh();removed=emitter.fresh()
                query=query_canonical(emitter,key,shape(kind.record.key))
                body='let '+removed+'='+self.cpython_sets.query(emitter,node,Expression(text,kind),key,remove=True)+';'
                if name=='remove':
                    from .native_integer_digit_limits import guard_error_repr
                    guard_error_repr(emitter,key,node)
                    failure=emitter.at('Err::<(),String>(format!("KeyError: {}",'+emitter.show(key,node,True)+'))',node)
                    body+='if !'+removed+'{'+failure+';}'
                return '{'+body+'()}'
            code=project(owner.kind,owner.code,branch)if union_kind(owner.kind)else branch(owner.kind,owner.code)
        elif name=='pop':
            from .native_unions import project,union_kind
            def branch(kind,text):
                item=emitter.fresh();taken=emitter.at('('+text+').borrow_mut().pop()',node)
                return '{let '+item+'='+taken+';'+emitter.coerce(Expression(item,shape(kind.record.key)),wanted,node)+'}'
            code=project(owner.kind,owner.code,branch)if union_kind(owner.kind)else branch(owner.kind,owner.code)
        else:
            default=arguments[1]if len(arguments)==2 else Expression('()','none')
            if name=='get':code=self.emit_get(emitter,node,owner,arguments[0],wanted,default).code
            else:
                from .native_unions import union_kind,project
                key=arguments[0]
                def branch(kind,text):
                    captured=Expression('('+text+').clone()',kind);value=emitter.fresh();record=kind.record
                    lookup=emitter.fresh()
                    query=query_canonical(emitter,key,shape(record.key));canonical_name=emitter.fresh()
                    found=f'{{let {lookup}=match {query}{{Some({canonical_name})=>{captured.code}.borrow().get(&{canonical_name}).cloned(),None=>None}};{lookup}}}'
                    present=emitter.coerce(Expression(value,shape(record.value)),wanted,node)
                    return 'match '+found+'{Some('+value+')=>'+present+',None=>{'+self.emit_store(emitter,node,captured,key,default)+emitter.coerce(default,wanted,node)+'}}'
                code=project(owner.kind,owner.code,branch)if union_kind(owner.kind)else branch(owner.kind,owner.code)
        return Expression('{'+setup+code+'}',wanted)

    def truth(self,emitter,value):
        return '{let value=!('+value.code+').borrow().is_empty();value}'

    def sorted_element(self,source,key,node):
        from .native_classes import Cell,shape,ClassUnsupported
        kinds=alternatives(shape(source))
        if not kinds or not all(mapping_kind(kind)for kind in kinds):return None
        if any(kind.record.category=='set'and not self.cpython_sets.owns(kind)for kind in kinds)and shape(key)!='none':
            raise ClassUnsupported(node,'a callable sorting key would expose set traversal and tie order; only proved key=None sorting is supported for typed sets',proof='order-insensitive set consumption')
        result=Cell()
        for kind in kinds:self.model.contribute(result,kind.record.key,node)
        return result

    def sorted_values(self,emitter,node,source,element):
        from .native_classes import Expression,shape,ClassUnsupported
        from .native_unions import project,union_kind
        def branch(kind,code):
            key=emitter.fresh();value=emitter.coerce(Expression(key+'.clone()',shape(kind.record.key)),element,node)
            entries='.entries().map(|('+key+',_,_)|'if kind.record.category=='set'else'.entries.iter().map(|('+key+',_)|'
            return '('+code+').borrow()'+entries+value+').collect::<Vec<'+emitter.rust_type(element)+'>>()'
        return project(source.kind,source.code,branch)if union_kind(source.kind)else branch(source.kind,source.code)

    def show(self,emitter,value,node):
        from .native_classes import Expression,shape,ClassUnsupported
        record=value.kind.record
        if record.flavor=='defaultdict':return self.defaultdicts.show(emitter,value,node)
        if record.flavor=='Counter':return self.counters.show(emitter,value,node)
        if record.category=='set':
            key,read,text=(emitter.fresh()for _ in range(3))
            shown=emitter.show(Expression(key+'.clone()',shape(record.key)),node,True)
            return '{let '+read+'=('+value.code+').borrow();let '+text+'=if '+read+'.is_empty(){"set()".to_owned()}else{format!("{{{}}}",'+read+'.entries().map(|('+key+',_,_)|'+shown+').collect::<Vec<_>>().join(", "))};'+text+'}'
        before,value=emitter.capture(Expression('('+value.code+').clone()',value.kind))
        key,item,read=(emitter.fresh()for _ in range(3))
        a=emitter.show(Expression(key+'.clone()',shape(record.key)),node,True)
        b=emitter.show(Expression(item+'.clone()',shape(record.value)),node,True)
        return '{'+before+f'let {read}={value.code}.borrow();format!("{{{{{{}}}}}}",{read}.entries.iter().map(|({key},{item})|format!("{{}}: {{}}",{a},{b})).collect::<Vec<_>>().join(", "))'+'}'

    def comparison(self,emitter,operator,left,right,node):
        from .native_classes import Expression,shape,ClassUnsupported
        if not mapping_kind(right.kind):return None
        record=right.kind.record
        if isinstance(operator,(ast.In,ast.NotIn)):
            if mapping_kind(left.kind)and left.kind.record.category=='set'and record.category=='set':
                from .native_cpython_set_adapters import frozenset_disjoint
                if not frozenset_disjoint(shape(record.key)):
                    raise ClassUnsupported(node,'mutable-set membership needs a frozenset fallback whose equality against this stored key family is not proved',types=(('stored key',shape(record.key)),),proof='set-query frozenset hash/equality fallback')
                # Both original operands are already captured by the comparison
                # emitter. CP's mutable-set fallback hashes retained entries and
                # cannot equal any key in this callback-free closed family.
                code='false'
            elif not key_supported(left.kind):
                from .native_class_builtins import _type_name
                from .native import _string
                leaf=unhashable_leaf(left.kind)
                if leaf is None:raise ClassUnsupported(node,'this dictionary/set membership key needs a floating/custom Python hash/equality adapter that is not implemented',types=(('key',left.kind),),proof='Python membership-key hash/equality protocol')
                purpose='dict key'if record.category=='dict'else'set element'
                message='"TypeError: cannot use \'{}\' as a '+purpose+' (unhashable type: \'{}\')"'
                code=emitter.at('Err::<bool,String>(format!('+message+','+query_type_name(emitter,left,node)+','+_string(leaf)+'))',node)
            else:
                key=emitter.fresh();query=query_canonical(emitter,left,shape(record.key))
                lookup=self.cpython_sets.query(emitter,node,right,left)if record.category=='set'else'match '+query+'{Some('+key+')=>'+right.code+'.borrow().contains(&'+key+'),None=>false}'
                code='{let value='+lookup+';value}'
            return '!('+code+')'if isinstance(operator,ast.NotIn)else code
        if mapping_kind(left.kind)and isinstance(operator,(ast.Is,ast.IsNot)):
            code='Rc::ptr_eq(&'+left.code+','+'&'+right.code+')'if left.kind==right.kind else'false'
            return '!('+code+')'if isinstance(operator,ast.IsNot)else code
        return None

    def runtime(self,emitter):
        from .native_classes import shape
        if not self.records:return ''
        from .native_ordered_entries import ORDERED_HELPERS,POSITIONED_HELPERS
        from .native_key_containers import HELPERS,BIG_HASH
        from .native_constraint_lowering import EMPTY_HELPERS
        dictionaries=any(record.category=='dict'for record in self.records)
        result=[POSITIONED_HELPERS if self.views.positions_enabled()else ORDERED_HELPERS,HELPERS]if dictionaries else[]
        tuple_runtime=getattr(self.model,'materialized_tuple',False)or any(plan.reachable and getattr(plan,'variadic_element',None)is not None for plan in self.model.plans)
        if not tuple_runtime and not any(record.emitted and isinstance(shape(record.element),EmptyType)for record in self.model.iterators.records):result.append(EMPTY_HELPERS)
        if self.model.integer=='bigint'and dictionaries:result.append(BIG_HASH)
        for record in self.records:
            key,value=shape(record.key),shape(record.value)
            payload=self.cpython_sets.payload(emitter,record)if record.category=='set'else self.defaultdicts.owner_type(record)if record.flavor=='defaultdict'else'RefCell<NativeKeyDict<'+emitter.rust_type(key)+','+emitter.rust_type(value)+','+canonical_type(key)+'>>'
            result.append('type ClassMapping_'+str(record.index)+'=Rc<'+payload+'>;')
        result.append(self.defaultdicts.runtime(emitter))
        result.append(self.views.runtime(emitter))
        result.append(self.cpython_sets.runtime())
        result.append(self.counters.runtime())
        from .native_mapping_method_callables import runtime as mapping_method_runtime
        result.append(mapping_method_runtime(self.model,emitter))
        from .native_mapping_popitem import runtime as popitem_runtime
        result.append(popitem_runtime(self.model))
        return '\n'.join(result)
