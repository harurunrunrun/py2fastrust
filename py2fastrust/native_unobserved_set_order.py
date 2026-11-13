"""Typed set materialization whose arbitrary traversal never becomes observable.

The proof follows a fresh builtin list through original binding owners. It is
recomputed after inference; provisional element transport never certifies order.
"""
import ast
from dataclasses import dataclass,field

from .references import BuiltinIdentity


class Unproved(Exception):pass


def requires_frames(unit,analysis):
    from .native_constraints import Allocation
    from .native_key_types import SetType
    return any(BuiltinIdentity('list')in call.identity.alternatives and call.positional
               and any(isinstance(part,SetType)or isinstance(part,Allocation)and part.category=='set'
                       for part in call.positional[0].alternatives)
               for facts in analysis.scopes.values()for call in facts.calls.values())


def _shape(cell):
    from .native_classes import shape
    return shape(cell)


def total_key(kind):
    from .native_types import EmptyType,TupleType,TupleSequenceType
    if isinstance(kind,EmptyType)or kind in {'int','bool','int_bool','str','bytes'}:return True
    if isinstance(kind,TupleType):return all(total_key(child)for child in kind.fields)
    return isinstance(kind,TupleSequenceType)and total_key(kind.element)


def safe_lifetime(kind,seen=frozenset()):
    from .native_types import ListType,TupleType,TupleSequenceType,alternatives,EmptyType
    from .native_class_mappings import mapping_kind
    if kind is None:return False
    if isinstance(kind,EmptyType)or kind in {'int','bool','int_bool','str','bytes','float','none','range'}:return True
    if kind in seen:return False
    seen=seen|{kind}
    if isinstance(kind,(ListType,TupleSequenceType)):return safe_lifetime(kind.element,seen)
    if isinstance(kind,TupleType):return all(safe_lifetime(k,seen)for k in kind.fields)
    if mapping_kind(kind):return all(safe_lifetime(_shape(c),seen)for c in (kind.record.key,kind.record.value))
    choices=alternatives(kind)
    return len(choices)>1 and all(safe_lifetime(k,seen)for k in choices)


@dataclass
class State:
    aliases:set=field(default_factory=set)
    ordered:bool=False
    bound:set=field(default_factory=set)
    def copy(self):return State(set(self.aliases),self.ordered,set(self.bound))


@dataclass
class Exit:
    state:State
    result:bool=False


class Proof:
    def __init__(self,model,producer,environment):
        self.model=model;self.producer=producer;self.active=set()
        self.definite=set(getattr(environment,'definite',environment or()))
        self.published=False
        self.parents={id(child):node for node in model.iter_nodes()for child in ast.iter_child_nodes(node)}

    def kind(self,plan,node):
        cell=self.model.records.get((plan.index,id(node)))
        return _shape(cell)if cell is not None else None

    def binding(self,plan,node):
        binding=self.model.lexical.binding(node)
        if binding is None:raise Unproved('a list alias lacks its official binding owner')
        return binding.owner,binding.name

    def same_execution(self,scope,owner):
        while scope is not None and self.model.unit.scopes[scope].kind=='comprehension':
            scope=self.model.unit.scopes[scope].parent
        return scope==owner

    def private_binding(self,plan,node):
        key=self.binding(plan,node)
        if key[0]!=self.model.lexical.scope(plan):raise Unproved('an unordered list escapes its current lexical scope')
        if any(b.owner==key[0]and b.name==key[1]and not self.same_execution(b.scope,key[0])
               for b in self.model.iter_bindings()):raise Unproved('a captured binding can expose the unordered list')
        return key

    def targets(self,plan,node):
        from .native_aot_callables import AotFunctionType
        kind=self.kind(plan,node)
        if isinstance(kind,AotFunctionType):return kind.targets
        if self.model.callable_cells.stable_direct(plan,node):
            target=self.model.functions[self.model.resolved_name(plan,node)]
            return (self.model.callable_cells.definition(target),)
        from .native_physical_list_builtins import static_builtin
        for name in ('sorted','len','bool','print'):
            if static_builtin(self.model,plan,node,name):return (BuiltinIdentity(name),)
        return ()

    @staticmethod
    def join(left,right):
        if left.ordered:return right.copy()if not right.ordered else State(ordered=True)
        if right.ordered:return left.copy()
        if left.aliases!=right.aliases:raise Unproved('conditional rebinding loses a definite alias to the original allocation')
        result=left.copy();result.bound&=right.bound
        return result

    def scalar(self,plan,node,state):
        if self.expression(plan,node,state):raise Unproved('an unordered list is consumed before order erasure')
        if self.kind(plan,node)not in {'int','bool','int_bool','float','str','bytes','none'}:
            raise Unproved('an expression may invoke a source conversion or finalizer before sorting')

    def sort(self,plan,node,state,*,method):
        site=getattr(self.model,'sorting_sites',{}).get((plan.index,id(node)))
        if site is None or site.error or _shape(site.key)!='none' or not total_key(_shape(site.element)):
            raise Unproved('the sort comparator is not proved total, builtin and nonfallible')
        for keyword in node.keywords:
            if keyword.arg not in {'key','reverse'}:raise Unproved('unregistered sorting keyword binding')
            self.scalar(plan,keyword.value,state)
            if keyword.arg=='key'and self.kind(plan,keyword.value)!='none':raise Unproved('a sorting callback can observe traversal order')
            if keyword.arg=='reverse'and self.kind(plan,keyword.value)not in {'bool','int','int_bool'}:raise Unproved('reverse conversion may call source code')
        if method:
            state.ordered=True;state.aliases.clear()

    def helper(self,plan,node,state,arguments):
        if self.published and not state.ordered:
            raise Unproved('a source callback can fail while an unsorted namespace binding is already published')
        targets=self.targets(plan,node.func)
        if len(targets)!=1 or not isinstance(targets[0],int):raise Unproved('an unproved callback can observe unsorted bindings')
        target=self.model.callable_cells.plans[targets[0]]
        if target.index in self.active or not isinstance(target.node,ast.FunctionDef):raise Unproved('recursive or nonfunction order-forwarding callback')
        from .call_semantics import normalize_call,CallBindingError
        try:binding=target.signature.plan(normalize_call(node))
        except CallBindingError:raise Unproved('forwarding callback binding is not closed')from None
        seeded=set()
        for name,source in zip(binding.parameters,binding.sources):
            if source.kind=='argument'and arguments[source.index]:
                seeded.add((self.model.lexical.scope(target),name))
            elif source.kind not in {'argument','default'}:raise Unproved('variadic forwarding can hide unordered aliases')
        if not seeded:raise Unproved('an unrelated callback may observe an unordered captured binding')
        # Only explicit parameters can introduce this allocation into a helper.
        for key in seeded:
            if any(b.owner==key[0]and b.name==key[1]and not self.same_execution(b.scope,key[0])for b in self.model.iter_bindings()):
                raise Unproved('a forwarding callback captures its unordered parameter')
        self.active.add(target.index)
        try:normal,exits=self.block(target,target.node.body,State(seeded))
        finally:self.active.remove(target.index)
        if normal is not None:exits.append(Exit(normal))
        if not exits:raise Unproved('forwarding callback has no proved normal or explicit return path')
        live=[exit for exit in exits if not exit.state.ordered]
        if not live:state.ordered=True;state.aliases.clear();return False
        if len({exit.result for exit in live})!=1:raise Unproved('a forwarding result may refer to different list allocations')
        return live[0].result

    def expression(self,plan,node,state):
        if node is self.producer:return True
        if isinstance(node,ast.Constant):return False
        if isinstance(node,ast.Name):
            key=self.binding(plan,node)
            if self.published and not state.ordered and key not in state.aliases and key not in state.bound:
                raise Unproved('a possibly unbound read can fail before published order erasure')
            return key in state.aliases
        if isinstance(node,ast.Call):
            if any(isinstance(a,ast.Starred)for a in node.args)or any(k.arg is None for k in node.keywords):raise Unproved('expanded arguments may hide alias effects')
            if isinstance(node.func,ast.Attribute)and node.func.attr=='sort':
                alias=self.expression(plan,node.func.value,state)
                if alias:
                    if node.args:raise Unproved('invalid sort binding does not erase order')
                    self.sort(plan,node,state,method=True);return False
            if not isinstance(node.func,ast.Name):
                raise Unproved('a callable attribute lookup has no closed effect certificate before sorting')
            targets=self.targets(plan,node.func)
            if self.published and not state.ordered:
                from .native_physical_list_builtins import static_builtin
                builtin=(len(targets)==1 and isinstance(targets[0],BuiltinIdentity)
                         and static_builtin(self.model,plan,node.func,targets[0].name))
                if not builtin and self.binding(plan,node.func)not in state.bound:
                    raise Unproved('a possibly unbound callee lookup can expose an unsorted namespace binding')
            arguments=[self.expression(plan,a,state)for a in node.args]
            arguments.extend(self.expression(plan,k.value,state)for k in node.keywords)
            for expression,alias in zip([*node.args,*(k.value for k in node.keywords)],arguments):
                if not alias and not safe_lifetime(self.kind(plan,expression)):
                    raise Unproved('a call argument can expose a source lifetime or conversion effect')
            if targets==(BuiltinIdentity('sorted'),):
                if len(node.args)!=1 or not arguments[0]:raise Unproved('sorting does not consume the tracked allocation')
                self.sort(plan,node,state,method=False);return False
            if targets==(BuiltinIdentity('print'),):
                if self.published and not state.ordered:
                    raise Unproved('an output failure can expose an unsorted namespace binding')
                if any(arguments):raise Unproved('printing an unordered list exposes traversal order')
                return False
            if targets in {(BuiltinIdentity('len'),),(BuiltinIdentity('bool'),)}:
                if len(node.args)!=1 or node.keywords:raise Unproved('invalid order-insensitive builtin binding')
                if self.published and not state.ordered and targets==(BuiltinIdentity('len'),):
                    from .native_types import ListType,TupleType,TupleSequenceType
                    value=self.kind(plan,node.args[0])
                    if value not in {'str','bytes'}and not isinstance(value,(ListType,TupleType,TupleSequenceType)):
                        raise Unproved('len() may raise before published order erasure')
                return False
            return self.helper(plan,node,state,arguments)
        if isinstance(node,ast.IfExp):
            self.scalar(plan,node.test,state)
            yes,no=state.copy(),state.copy()
            a=self.expression(plan,node.body,yes);b=self.expression(plan,node.orelse,no)
            joined=self.join(yes,no)
            if not yes.ordered and not no.ordered and a!=b:raise Unproved('conditional expression loses a definite list allocation')
            state.aliases, state.ordered=joined.aliases,joined.ordered
            return (a if not yes.ordered else False)or(b if not no.ordered else False)
        if isinstance(node,(ast.UnaryOp,ast.BinOp,ast.BoolOp,ast.Compare)):
            if self.published and not state.ordered:
                raise Unproved('an operator can fail before published order erasure')
            values=([node.operand]if isinstance(node,ast.UnaryOp)else[node.left,node.right]if isinstance(node,ast.BinOp)
                    else node.values if isinstance(node,ast.BoolOp)else[node.left,*node.comparators])
            for index,value in enumerate(values):
                if (isinstance(node,ast.BoolOp)and index>0
                        or isinstance(node,ast.Compare)and index>1):
                    taken=state.copy();self.scalar(plan,value,taken);joined=self.join(state,taken)
                    state.aliases,state.ordered=joined.aliases,joined.ordered
                else:self.scalar(plan,value,state)
            return False
        if isinstance(node,(ast.Tuple,ast.List,ast.Set,ast.Dict)):
            if self.published and not state.ordered and isinstance(node,(ast.Set,ast.Dict)):
                raise Unproved('a hash operation can fail before published order erasure')
            values=([value for pair in zip(node.keys,node.values)for value in pair if value is not None]if isinstance(node,ast.Dict)else node.elts)
            for value in values:
                if self.expression(plan,value,state):raise Unproved('an unordered list escapes inside a container')
                if not safe_lifetime(self.kind(plan,value)):raise Unproved('container lifetime may trigger a source finalizer')
            return False
        raise Unproved('this expression can expose traversal order or call user code before sorting')

    def assign(self,plan,target,alias,state):
        if not isinstance(target,ast.Name):raise Unproved('an assignment can publish an unordered list through shared storage')
        key=self.private_binding(plan,target)
        old=self.kind(plan,target)
        if old is not None and not safe_lifetime(old):raise Unproved('overwriting a binding may run a source finalizer')
        state.aliases.discard(key);state.bound.add(key)
        if alias and not state.ordered:state.aliases.add(key)

    def block(self,plan,statements,state):
        exits=[]
        for node in statements:
            if state.ordered:return state,exits
            if isinstance(node,(ast.Assign,ast.AnnAssign)):
                if node.value is None:continue
                alias=self.expression(plan,node.value,state)
                for target in node.targets if isinstance(node,ast.Assign)else[node.target]:self.assign(plan,target,alias,state)
            elif isinstance(node,ast.Expr):
                if self.expression(plan,node.value,state):raise Unproved('an unordered list expression can expose its value')
            elif isinstance(node,ast.If):
                self.scalar(plan,node.test,state)
                yes,first=self.block(plan,node.body,state.copy());no,second=self.block(plan,node.orelse,state.copy())
                exits+=first+second
                if yes is None:state=no
                elif no is None:state=yes
                else:state=self.join(yes,no)
                if state is None:return None,exits
            elif isinstance(node,ast.Return):
                alias=False if node.value is None else self.expression(plan,node.value,state)
                if node.value is not None and not alias and not safe_lifetime(self.kind(plan,node.value)):
                    raise Unproved('a returned value may trigger a source finalizer before caller order erasure')
                exits.append(Exit(state.copy(),alias));return None,exits
            elif isinstance(node,ast.Pass):pass
            else:raise Unproved('control flow, cleanup or a callback may observe the list before sorting')
        return state,exits

    def prove(self,plan,node):
        from .native_owned_local_lists import observes_frames
        if observes_frames(self.model):raise Unproved('frame or namespace observers can expose the provisional list')
        statement=self.parents.get(id(node))
        if not isinstance(statement,(ast.Assign,ast.AnnAssign))or statement.value is not node:
            raise Unproved('the fresh list is not introduced by an isolated lexical assignment')
        if statement not in plan.node.body:raise Unproved('the materialization has an enclosing cleanup or control-flow continuation')
        targets=statement.targets if isinstance(statement,ast.Assign)else[statement.target]
        local_frame=isinstance(plan.node,ast.FunctionDef)and plan.class_body is None
        self.published=not local_frame
        state=State()
        scope=self.model.lexical.scope(plan)
        for name in self.model.iter_nodes():
            if isinstance(name,ast.Name)and self.model.resolved_name(plan,name)in self.definite:
                key=self.binding(plan,name)
                if key[0]==scope:state.bound.add(key)
        for target in targets:self.assign(plan,target,True,state)
        start=plan.node.body.index(statement)+1
        normal,exits=self.block(plan,plan.node.body[start:],state)
        if normal is not None:exits.append(Exit(normal))
        if any(not exit.state.ordered and (not local_frame and exit.state.aliases or exit.result)for exit in exits):
            raise Unproved('not every escaping continuation erases the original allocation order')
        return True


class SetCursor:
    @staticmethod
    def owned(record):return (_shape(record.source),)
    @staticmethod
    def demand(registry,plan,node,record,environment,active):return record.element
    @staticmethod
    def may_call(registry,record,seen):return False
    @staticmethod
    def fields(emitter,record):return 'source:Option<'+emitter.rust_type(_shape(record.source))+'>,expected:usize,slot:usize'
    @staticmethod
    def pull(registry,emitter,node,value,active):
        from .native_classes import Expression
        from .native_unions import project
        record=value.kind.record;wanted=_shape(record.element)
        state,source,item,read,slot=(emitter.fresh()for _ in range(5))
        def branch(kind,code):
            converted=emitter.coerce(Expression(read+'.entries['+slot+'].0.clone()',_shape(kind.record.key)),wanted,node)
            return ('{let '+read+'=('+code+').borrow();'
                    'if '+read+'.len()!='+state+'.expected{'+emitter.at('Err::<(),String>("RuntimeError: Set changed size during iteration".to_owned())',node)+';}'
                    'let '+slot+'='+state+'.slot;if '+slot+'==NATIVE_ENTRY_NONE{None}else{'+state+'.slot='+read+'.entries.slots['+slot+'].next;Some('+converted+')}}')
        pulled=project(_shape(record.source),source,branch)
        code='{let mut '+state+'='+value.code+'.borrow_mut();let '+item+'=match '+state+'.source.clone(){Some('+source+')=>'+pulled+',None=>None};if '+item+'.is_none(){'+state+'.source=None;}'+item+'}'
        return Expression(code,wanted)


def source(model,plan,node,value,environment=None):
    from .native_classes import Cell,ClassUnsupported
    from .native_class_mappings import mapping_kind
    from .native_types import alternatives
    kinds=alternatives(_shape(value))
    if not kinds or not all(mapping_kind(kind)and kind.record.category=='set'for kind in kinds):return None
    record=model.iterators._record(plan,node,'unobserved_set_list')
    record.adapter=SetCursor
    model.iterators._contribute(record.source,value,node)
    for kind in kinds:model.iterators._contribute(record.element,kind.record.key,node)
    if model.final:
        try:
            if not total_key(_shape(record.element)):raise Unproved('the set keys lack a total builtin sorting order')
            Proof(model,node,environment).prove(plan,node)
        except Unproved as error:
            raise ClassUnsupported(node,'materializing this set as a list would expose unspecified traversal order: '+str(error),types=(('set element',_shape(record.element)),),proof='unobserved set traversal followed by total order erasure')from None
    return Cell(record.kind)


def selected(model,plan,node,kind):
    from .native_class_mappings import mapping_kind
    from .native_types import alternatives
    return ((plan.index,id(node),'unobserved_set_list',None)in model.iterators.sites
            and all(mapping_kind(part)and part.record.category=='set'for part in alternatives(kind)))


def construct(emitter,node,value):
    from .native_classes import Expression
    from .native_unions import project
    record=emitter.model.iterators.sites[emitter.plan.index,id(node),'unobserved_set_list',None]
    record.emitted=True
    before,owner=emitter.capture(value)
    length,slot=(emitter.fresh()for _ in range(2))
    pair=project(owner.kind,owner.code,lambda kind,code:'{let read=('+code+').borrow();(read.len(),read.entries.head)}')
    before+='let ('+length+','+slot+')='+pair+';'
    payload=emitter.coerce(owner,_shape(record.source),node)
    return Expression('{'+before+'Rc::new(RefCell::new(ClassIteratorState_'+str(record.index)+'{source:Some('+payload+'),expected:'+length+',slot:'+slot+'}))}',record.kind)
