"""Source-bound typed CP set storage and original-AST construction adapters."""
import ast

from .native_types import EmptyType,TupleType,TupleSequenceType


def requires_frames(unit,analysis):
    from .native_constraints import Allocation
    from .native_key_types import SetType
    from .references import BuiltinIdentity
    from .native_types import alternatives
    def actual(value):
        return any(isinstance(part,SetType)or isinstance(part,Allocation)and part.category=='set'
                   for part in getattr(value,'alternatives',()))
    observers={'iter','list','tuple','print','str','repr','reversed','enumerate','map','filter','zip'}
    for facts in analysis.scopes.values():
        for call in facts.calls.values():
            if any(BuiltinIdentity(name)in call.identity.alternatives for name in observers)and any(actual(value)for value in call.positional):return True
            if any(BuiltinIdentity(name)in call.identity.alternatives for name in {'sorted','min','max'}):
                if any(name=='key'and value.alternatives!={'none'}for name,value in call.keywords)and any(actual(value)for value in call.positional):return True
    for node in ast.walk(unit.tree):
        if isinstance(node,ast.Call)and isinstance(node.func,ast.Attribute)and node.func.attr=='pop':
            ordinal=unit.ordinal(node.func.value)
            if any(actual(facts.values.get(ordinal))or any(isinstance(kind,SetType)for kind in alternatives(facts.expressions.get(ordinal)))for facts in analysis.scopes.values()):return True
        source=(node.iter if isinstance(node,(ast.For,ast.comprehension))else node.value if isinstance(node,(ast.Starred,ast.FormattedValue))else None)
        if source is None:continue
        ordinal=unit.ordinal(source)
        for facts in analysis.scopes.values():
            if actual(facts.values.get(ordinal)):return True
            if any(isinstance(kind,SetType)for kind in alternatives(facts.expressions.get(ordinal))):return True
    return False


def _canonical_field(code,size,index):
    if size<=12:return '('+code+').'+str(index)
    midpoint=size//2
    return _canonical_field('('+code+').'+('0'if index<midpoint else'1'),midpoint if index<midpoint else size-midpoint,index if index<midpoint else index-midpoint)


def requires_secret(kind):
    from .native_numeric_keys import common_key
    kind=common_key(kind)
    if kind in {'str','bytes'}:return True
    if isinstance(kind,TupleType):return any(requires_secret(child)for child in kind.fields)
    if isinstance(kind,TupleSequenceType):return requires_secret(kind.element)
    return False


def frozenset_disjoint(kind):
    """Closed builtin equality families that cannot equal a set/frozenset.

The native key guard already excludes callback-bearing hash/equality. Keep
nominal tuple subclasses outside this certificate even when their payload
currently resembles an ordinary tuple.
"""
    from .native_numeric_keys import numeric
    if numeric(kind)or isinstance(kind,EmptyType)or kind in {'str','bytes','none'}:return True
    if type(kind)is TupleType:return all(frozenset_disjoint(child)for child in kind.fields)
    if type(kind)is TupleSequenceType:return frozenset_disjoint(kind.element)
    return False


def canonical_hash(emitter,kind,code):
    from .native_numeric_keys import common_key
    kind=common_key(kind)
    if isinstance(kind,EmptyType):return 'match '+code+'{}'
    from .native_numeric_keys import numeric,floating
    if numeric(kind)and floating(kind):return 'native_numeric_key_hash(&('+code+'))'
    if kind in {'int','bool','int_bool'}:return 'native_cp_hash_native(&('+code+'))'
    if kind=='none':return 'native_cp_hash_none()'
    if kind=='str':
        return ('native_cp_hash_bytes(('+code+').as_bytes(),native_cp_program_secret())'if emitter.model.string_mode=='ascii'else
                'native_cp_hash_text(&('+code+'),native_cp_program_secret())')
    if kind=='bytes':return 'native_cp_hash_bytes(&('+code+'),native_cp_program_secret())'
    if isinstance(kind,TupleType):
        fields=[canonical_hash(emitter,child,_canonical_field(code,len(kind.fields),index))for index,child in enumerate(kind.fields)]
        return 'native_cp_hash_tuple(['+','.join(fields)+'])'
    if isinstance(kind,TupleSequenceType):
        item=emitter.fresh()
        return 'native_cp_hash_tuple(('+code+').iter().map(|'+item+'|'+canonical_hash(emitter,kind.element,'(*'+item+')')+'))'
    raise KeyError(kind)


class CPythonSets:
    def __init__(self,mappings):
        self.mappings=mappings;self.model=mappings.model;self.literal_plans={}
        self.parents=None;self.constant_origins=None

    def owns(self,kind):
        return self.mappings.owns(kind)and kind.record.category=='set'

    def new(self,emitter,record):
        from .native_classes import shape
        from .native_class_mappings import canonical_type
        record.emitted=True;key=shape(record.key)
        return 'Rc::new(RefCell::new(NativeCPSet::<'+emitter.rust_type(key)+','+canonical_type(key)+'>::new()))'

    def payload(self,emitter,record):
        from .native_classes import shape
        from .native_class_mappings import canonical_type
        key=shape(record.key)
        return 'RefCell<NativeCPSet<'+emitter.rust_type(key)+','+canonical_type(key)+'>>'

    def insert(self,emitter,node,owner,key):
        from .native_classes import shape,Expression
        from .native_class_mappings import canonical
        owner.kind.record.emitted=True
        wanted=shape(owner.kind.record.key);name,canonical_name,hashed=(emitter.fresh()for _ in range(3))
        retained=emitter.coerce(Expression('('+key.code+').clone()',key.kind),wanted,node)
        return ('let '+name+':'+emitter.rust_type(wanted)+'='+retained+';let '+canonical_name+'='+canonical(emitter,Expression(name,wanted))+';let '+hashed+'='+canonical_hash(emitter,wanted,canonical_name)+';'+
                emitter.at(owner.code+'.borrow_mut().add('+name+','+canonical_name+','+hashed+')',node)+';')

    def query(self,emitter,node,owner,key,*,remove=False):
        from .native_classes import shape
        from .native_class_mappings import query_canonical
        owner.kind.record.emitted=True
        kind=shape(owner.kind.record.key);name=emitter.fresh()
        query=query_canonical(emitter,key,kind)
        return ('match '+query+'{Some('+name+')=>('+owner.code+').'+('borrow_mut().discard'if remove else'borrow().contains')+
                '(&'+name+','+canonical_hash(emitter,kind,name)+'),None=>false}')

    def merge(self,emitter,node,owner,source):
        from .native_classes import Expression,shape
        from .native_class_mappings import canonical
        other,loan,key,stored=(emitter.fresh()for _ in range(4))
        wanted=shape(owner.kind.record.key);actual=shape(source.kind.record.key)
        converted=emitter.coerce(Expression(key+'.clone()',actual),wanted,node)
        canonical_source=emitter.fresh()
        copied=canonical_source+'.clone()'if wanted==actual else canonical(emitter,Expression(stored,wanted))
        converter='|'+key+','+canonical_source+'|{let '+stored+':'+emitter.rust_type(wanted)+'='+converted+';let canonical='+copied+';('+stored+',canonical)}'
        body='let '+other+'=('+source.code+').clone();let '+loan+'='+other+'.borrow();'+emitter.at(owner.code+'.borrow_mut().merge_projected(&*'+loan+','+converter+')',node)+';'
        if self.payload(emitter,owner.kind.record)==self.payload(emitter,source.kind.record):
            return '{if !Rc::ptr_eq(&'+owner.code+',&('+source.code+')){'+body+'}}'
        return '{'+body+'}'

    def from_mapping(self,emitter,node,owner,source):
        from .native_classes import Expression,shape
        if source.kind.record.category=='set':return self.merge(emitter,node,owner,source)
        other,loan,key=(emitter.fresh()for _ in range(3))
        prepare=(emitter.at(owner.code+'.borrow_mut().prepare_dict_update('+loan+'.len())',node)+';'if source.kind.record.flavor=='dict'else'')
        return ('{let '+other+'=('+source.code+').clone();let '+loan+'='+other+'.borrow();'+prepare+
                'for ('+key+',_)in '+loan+'.entries.iter(){'+self.insert(emitter,node,owner,Expression(key+'.clone()',shape(source.kind.record.key)))+'}}')

    def plan_literal(self,node):
        if id(node)in self.literal_plans:return self.literal_plans[id(node)]
        if self.parents is None:
            # Compiler constants can originate in lazy annotations and unused
            # code omitted by the executable-node lowering view.
            units=getattr(self.model.unit,'source_units',(self.model.unit,))
            self.parents={id(child):parent for unit in units for parent in ast.walk(unit.tree)for child in ast.iter_child_nodes(parent)}
        if id(node)not in self.parents:
            from .native_classes import ClassUnsupported
            raise ClassUnsupported(node,'this set literal has no original AST observation context registered for its source unit',proof='original set construction parent metadata')
        from .native_cpython_set_context import construction_plan
        plan=construction_plan(self.model,node,self.parents)
        if plan in {'frozen_direct','frozen_bulk'}:
            if self.constant_origins is None:
                from .native_cpython_set_constants import ConstantOrigins
                self.constant_origins=ConstantOrigins(self.model,self.parents)
        self.literal_plans[id(node)]=plan;return plan

    def literal(self,emitter,node,wanted):
        from .native_classes import Expression
        record=wanted.record;record.emitted=True;plan=self.plan_literal(node)
        if plan in {'frozen_direct','frozen_bulk'}:
            from .native_cpython_set_interning import certify,unobserved
            proved=[]
            def order_irrelevant():
                if not proved:proved.append(unobserved(emitter.model,emitter.plan,node,self.parents))
                return proved[0]
            self.constant_origins.certify(node,order_irrelevant=order_irrelevant)
            certify(emitter,node,record,self,order_irrelevant)
        owner=emitter.fresh();prefix='';items=[]
        if plan!='incremental':
            for original in node.elts:
                before,item=emitter.capture(emitter.expression(original));prefix+=before;items.append(item)
        prefix+='let '+owner+'='+self.new(emitter,record)+';'
        if plan=='incremental':
            for original in node.elts:
                before,item=emitter.capture(emitter.expression(original));prefix+=before+self.insert(emitter,node,Expression(owner,wanted),item)
        else:
            for item in items:prefix+=self.insert(emitter,node,Expression(owner,wanted),item)
        if plan=='frozen_bulk':
            destination=emitter.fresh();prefix+='let '+destination+'='+self.new(emitter,record)+';'
            prefix+=self.merge(emitter,node,Expression(destination,wanted),Expression(owner,wanted));owner=destination
        return Expression('{'+prefix+owner+'}',wanted)

    def needs_secret(self):
        from .native_classes import shape
        return any(record.emitted and record.category=='set'and requires_secret(shape(record.key))for record in self.mappings.records)

    def runtime(self):
        if not any(record.category=='set'for record in self.mappings.records):return ''
        from .native_cpython_hash import RUNTIME as HASH
        from .native_cpython_set_runtime import RUNTIME as SET
        native=('match &value.0{IntRepr::Small(number)=>native_cp_hash_integer(*number),IntRepr::Big{negative,digits}=>native_cp_hash_digits(*negative,digits)}'if self.model.integer=='bigint'else'native_cp_hash_integer(*value as i128)')
        from .native_cpython_hash_secret import RUNTIME as SECRET
        roots=set()
        def hash_roots(kind):
            from .native_numeric_keys import numeric,floating,common_key
            kind=common_key(kind)
            if numeric(kind)and floating(kind):roots.add('native_numeric_key_hash')
            elif kind in {'int','bool','int_bool'}:roots.add('native_cp_hash_native')
            elif kind=='none':roots.add('native_cp_hash_none')
            elif kind=='str':roots.add('native_cp_hash_bytes'if self.model.string_mode=='ascii'else'native_cp_hash_text')
            elif kind=='bytes':roots.add('native_cp_hash_bytes')
            elif isinstance(kind,(TupleType,TupleSequenceType)):
                roots.add('native_cp_hash_tuple')
                for child in kind.fields if isinstance(kind,TupleType)else(kind.element,):hash_roots(child)
        from .native_classes import shape
        for record in self.mappings.records:
            if record.emitted and record.category=='set':hash_roots(shape(record.key))
        if self.needs_secret():roots.update(('native_cp_initialize_secret','native_cp_program_secret'))
        from .rust_pruning import prune_rust_source
        helpers=HASH+'\nfn native_cp_hash_native(value:&NativeInt)->i64{'+native+'}\n'+(SECRET if self.needs_secret()else'')
        return prune_rust_source(helpers,roots=tuple(sorted(roots)))+'\n'+SET

    def entry(self):
        return ('if let Err(error)=native_cp_initialize_secret(){eprintln!("{}",error);std::process::exit(1);}'if self.needs_secret()else'')
