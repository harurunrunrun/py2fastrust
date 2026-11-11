"""Source-specific typed heap continuations for closed ordinary call regions.

This is a calling convention for compiled source blocks, not an instruction
interpreter. Source locals and captured values keep concrete Rust types.
"""
import ast
from dataclasses import dataclass,field
from types import MethodType


class Unproved(Exception):pass


SCALARS=frozenset({'int','bool','int_bool','none','float','str','bytes'})


@dataclass
class Block:
    code:list=field(default_factory=list)
    end:object=None


@dataclass
class Site:
    index:int
    caller:object
    callee:object
    node:object
    arguments:tuple
    destination:object
    resume:int
    owned_child:bool=False


class Registry:
    def __init__(self,model):
        self.model=model;self.plans={};self.reason=None;self.builders={};self.sites=[]
        self.targets={};self.result_entries=set();self.invocations=None;self.captured={}
        self.parents={id(child):node for node in model.iter_nodes()for child in ast.iter_child_nodes(node)}
        try:self.prove()
        except Unproved as error:
            self.reason=str(error);self.plans.clear();self.targets.clear()
            from .native_captured_invocations import install_regions
            install_regions(self)
            return
        # Explicitly certify source entries; constructor wrappers remain a
        # separate physical role and must already be bounded/direct here.
        self.result_entries={plan.index for plan in model.plans if plan.reachable
                             and(plan is model.module or plan.index in self.plans)}

    def omitted(self,plan,node):
        reached=getattr(self.model,'reached_statements',None)
        if reached is None:return False
        while node is not None and not isinstance(node,ast.stmt):node=self.parents.get(id(node))
        return node is not None and(plan.index,id(node))not in reached

    def source(self,plan):
        from .native_frame_specialization import source_plan
        return source_plan(plan)

    def prove(self):
        from .native_classes import shape
        from .native_class_calls import synchronous
        from .native_aot_callables import AotFunctionType
        from .references import BuiltinIdentity
        from .native_module_calls import BuiltinRef
        from .native_invocation_control import InvocationLedger,owned_kind,contains_instance,canonical_identities
        self.invocations=InvocationLedger(self.model,self.source)
        if self.model.classes:
            if getattr(self.model,'module_linker',None)is not None:
                raise Unproved('retained linked class/function generations need owned invocation context fields')
            if self.model.unit is None:raise Unproved('class bindings need the official source graph')
            binding_rows=tuple(self.model.iter_bindings())
            for owner in self.model.classes.values():
                writes=[row for row in binding_rows if row.owner==0 and row.name==self.model.class_key(owner)and row.role!='load']
                if(len(writes)!=1 or writes[0].role!='definition'
                        or writes[0].node!=self.model.unit.ordinal(owner.node)):
                    raise Unproved('the source class binding has another producer/generation')
                if(owner.node not in self.model.tree.body or owner.node.bases or owner.node.keywords
                        or owner.node.decorator_list or owner.node.type_params
                        or any(not isinstance(child,(ast.FunctionDef,ast.Pass))for child in owner.node.body)):
                    raise Unproved('class publication effects need their own invocation control producer')
                for member in owner.node.body:
                    if isinstance(member,ast.FunctionDef)and(member.decorator_list or member.type_params
                            or member.args.defaults or member.args.kw_defaults):
                        raise Unproved('class member definition effects need their own publication producer')
                if any(name in owner.methods for name in ('__new__','__del__','__getattribute__','__getattr__','__setattr__','__delattr__')):
                    raise Unproved('custom allocation/attribute/lifetime protocols need typed invocation control')
                if set(owner.fields)&(set(owner.methods)|{'__dict__','__weakref__'}):
                    raise Unproved('an instance field can replace a direct method binding')
                initializer=owner.methods.get('__init__')
                if initializer is not None and not synchronous(self.model,initializer):
                    raise Unproved('suspending construction needs a distinct object-returning ConstructorEntry')
                from .native_owned_object_places import selected as unique_owned
                if unique_owned(self.model,owner):
                    raise Unproved('a unique owned object receiver needs a stable cross-frame place')
        if self.model.classes:
            from .native_invocation_control import method_binding_write_closed
            for plan in self.model.plans:
                if not plan.reachable:continue
                for node in self.model.value_classes.own_nodes(plan):
                    if self.omitted(plan,node):continue
                    if isinstance(node,ast.Attribute)and isinstance(node.ctx,(ast.Store,ast.Del)):
                        if not method_binding_write_closed(self.model,plan,node):
                            raise Unproved('a class/instance method write or unknown receiver breaks immutable method lookup')
            identities=set(self.model.callable_cells.builtin_used)|set(self.model.callable_cells.member_used)
            for stored in self.model.records.values():identities.update(canonical_identities(shape(stored)))
            if any((isinstance(target,BuiltinIdentity)or isinstance(target,BuiltinRef)and target.module=='builtins')and target.name in {'id','hash','repr','vars','dir','locals','globals','eval','exec','compile','getattr','setattr','delattr','type','__import__'}
                    or isinstance(target,BuiltinRef)and target.module=='sys'and target.name not in {'getrecursionlimit','setrecursionlimit'}for target in identities):
                raise Unproved('a retained native observer/callback needs exact frame lifetime coverage')
        if self.model.gc_classes:raise Unproved('collector frame roots require an explicit continuation layout')
        if self.model.exceptions.used:raise Unproved('retained exception payload/origin state needs a continuation policy')
        region=[plan for plan in self.model.plans if plan.reachable and plan is not self.model.module and not synchronous(self.model,plan)]
        if not region:raise Unproved('no ordinary heap continuation region is needed')
        functions={self.source(plan).node: self.source(plan)for plan in self.model.functions.definitions.values()}
        definition_positions={id(node):index for index,node in enumerate(self.model.tree.body)
                              if isinstance(node,(ast.FunctionDef,ast.ClassDef))}
        last_definition=max(definition_positions.values(),default=-1)
        self.static_callees=set()
        for plan in self.model.plans:
            if not plan.reachable or plan is self.model.module:continue
            source=self.source(plan)
            if getattr(source,'class_body',None)is not None:
                if not synchronous(self.model,plan):raise Unproved('suspending class publication needs an owned class-body entry')
                continue
            method=(source.owner is not None and source.node in source.owner.node.body)
            if not isinstance(source.node,ast.FunctionDef)or not(method or source.node in self.model.tree.body):
                raise Unproved('nested/implicit source activations require continuation environment support')
            if self.model.lexical.signature(plan):
                raise Unproved('a runtime lexical environment is not an owned ordinary scalar activation')
            args=source.node.args
            if(source.node.decorator_list or source.node.type_params or args.defaults or args.kw_defaults
                    or args.vararg or args.kwarg or args.kwonlyargs):
                raise Unproved('captured defaults/decorators/variadic signatures are not yet continuation-normalized')
            locals=[cell for values in plan.locals.values()for cell in values]
            if any(not owned_kind(self.model,shape(cell))for cell in [*plan.arguments.values(),plan.result,*locals]):
                raise Unproved('ordinary continuation locals/parameters/results are not closed owned scalar slots')
            if any(len({shape(cell)for cell in values})>1 for values in plan.locals.values()):
                raise Unproved('type-changing local clearing needs a physical frame-place rule')
        forbidden=(ast.ClassDef,ast.Lambda,ast.GeneratorExp,ast.With,ast.AsyncWith,ast.Try,ast.TryStar,ast.Yield,ast.YieldFrom,ast.Await,ast.TypeAlias)
        for plan in self.model.plans:
            if not plan.reachable:continue
            source=self.source(plan)
            if getattr(source,'class_body',None)is not None:continue
            own=list(source.node.body if isinstance(source.node.body,list)else[source.node.body])
            stack=list(reversed(own))
            while stack:
                node=stack.pop()
                if self.omitted(plan,node):continue
                if isinstance(node,ast.ClassDef)and node in self.model.tree.body:
                    owner=next((owner for owner in self.model.classes.values()if owner.node is node),None)
                    if owner is None:raise Unproved('class publication lacks an original owner')
                    body=getattr(owner,'body_plan',None)
                    if body is not None and not synchronous(self.model,body):
                        raise Unproved('class publication would reenter a typed source region')
                    continue
                if isinstance(node,ast.FunctionDef):
                    if plan is not self.model.module:raise Unproved('nested function binding is not normalized')
                    if node not in self.model.tree.body or node.decorator_list or node.args.defaults or node.args.kw_defaults or node.type_params:
                        raise Unproved('definition-time effects or conditional definitions require typed continuation capture')
                    continue
                if isinstance(node,forbidden):raise Unproved('cleanup/generator/class suspension is not yet continuation-normalized')
                if isinstance(node,ast.Import)and any(alias.name!='sys'for alias in node.names):
                    raise Unproved('source/module import activation is not yet continuation-normalized')
                if isinstance(node,ast.ImportFrom):raise Unproved('imported callable/module identities need continuation capture support')
                if isinstance(node,(ast.NamedExpr,ast.Delete)):raise Unproved('this binding mutation needs an explicit continuation place')
                if isinstance(node,ast.Name)and isinstance(node.ctx,ast.Load)and node.id in {'__annotations__','__annotate__'}:
                    raise Unproved('lazy annotation activation is not continuation-normalized')
                if self.model.classes and isinstance(node,ast.FormattedValue):
                    stored=self.model.records.get((plan.index,id(node.value)))
                    if stored is None or contains_instance(shape(stored)):
                        raise Unproved('formatted object representation needs exact temporary lifetime coverage')
                if self.model.classes and isinstance(node,ast.BinOp)and isinstance(node.op,ast.Mod):
                    first=self.model.records.get((plan.index,id(node.left)))
                    second=self.model.records.get((plan.index,id(node.right)))
                    if first is not None and shape(first)in {'str','bytes'}and(second is None or contains_instance(shape(second))):
                        raise Unproved('object percent formatting needs exact temporary lifetime coverage')
                if isinstance(node,ast.AnnAssign)and any(isinstance(part,(ast.Call,ast.NamedExpr,ast.Lambda))for part in ast.walk(node.annotation)):
                    raise Unproved('effectful lazy annotations require their own source activation descriptor')
                if isinstance(node,ast.Name)and isinstance(node.ctx,(ast.Store,ast.Del)):
                    name=self.model.resolved_name(plan,node)
                    if name in self.model.functions or name in self.model.classes:raise Unproved('a source callable/class binding can change during argument evaluation')
                if isinstance(node,ast.Name)and isinstance(node.ctx,ast.Load)and self.model.resolved_name(plan,node)in self.model.functions:
                    parent=self.parents.get(id(node))
                    if not isinstance(parent,ast.Call)or parent.func is not node:
                        raise Unproved('source function values escape their proved call-only binding')
                if self.model.classes and isinstance(node,(ast.Name,ast.Attribute))and isinstance(node.ctx,ast.Load):
                    stored=self.model.records.get((plan.index,id(node)))
                    identities=canonical_identities(None if stored is None else shape(stored))
                    parent=self.parents.get(id(node))
                    if not(isinstance(parent,ast.Call)and parent.func is node)and any(
                            (isinstance(target,BuiltinIdentity)or isinstance(target,BuiltinRef)and target.module=='builtins')
                            and target.name in {'print','str','format','ascii'}for target in identities):
                        raise Unproved('a retained representation callback needs its typed argument/lifetime ledger')
                if isinstance(node,ast.Call):
                    cell=self.model.records.get((plan.index,id(node.func)))
                    kind=None if cell is None else shape(cell)
                    if isinstance(node.func,ast.Attribute):
                        receiver=self.model.records.get((plan.index,id(node.func.value)))
                        if receiver is not None and shape(receiver)=='sys'and node.func.attr not in {'getrecursionlimit','setrecursionlimit'}:
                            raise Unproved('this canonical sys protocol has no continuation outcome policy')
                    from .native_types import alternatives
                    from .native_physical_list_builtins import static_builtin
                    identities=set()
                    for part in alternatives(kind):
                        if isinstance(part,(BuiltinIdentity,BuiltinRef)):identities.add(part)
                        identities.update(getattr(part,'targets',()))
                    site=getattr(self.model.callable_cells,'sites',{}).get((plan.index,id(node)))
                    if site is not None:
                        for family in ('targets','builtins','members','errors'):
                            identities.update(getattr(site,family,{}))
                    if isinstance(node.func,ast.Name)and static_builtin(self.model,plan,node.func,node.func.id):
                        identities.add(BuiltinIdentity(node.func.id))
                    if self.model.classes and any((isinstance(target,BuiltinIdentity)or isinstance(target,BuiltinRef)and target.module=='builtins')and target.name in {'print','str','format','ascii'}for target in identities):
                        operands=[*node.args,*(keyword.value for keyword in node.keywords)]
                        for operand in operands:
                            if isinstance(operand,ast.Starred):operand=operand.value
                            stored=self.model.records.get((plan.index,id(operand)))
                            if stored is None or contains_instance(shape(stored)):
                                raise Unproved('object representation observation needs exact temporary lifetime coverage')
                    if any((isinstance(target,BuiltinIdentity)or isinstance(target,BuiltinRef)and target.module=='builtins')and target.name in{
                        'id','hash','repr','dir','vars','locals','globals','eval','exec','compile','getattr','setattr','delattr','type','__import__','exit','quit'}
                        or isinstance(target,BuiltinRef)and(target.module not in {'builtins','sys'}or target.module=='sys'and target.name not in {'getrecursionlimit','setrecursionlimit'})for target in identities):
                        raise Unproved('an observer/native payload has no closed continuation lifetime policy')
                    targets=self.model.call_edges_by_site.get((plan.index,id(node)),())
                    if not targets and isinstance(node.func,ast.Name):
                        owner=self.model.classes.get(self.model.resolved_name(plan,node.func))
                        if owner is not None and owner.methods.get('__init__')is None:
                            self.invocations.bounded_constructor(plan,node,owner)
                    if targets:
                        producer=self.invocations.describe(plan,node,targets)
                        if producer.role=='constructor':
                            if producer.callee is None or not synchronous(self.model,producer.callee):
                                raise Unproved('constructor object result needs an owned synthetic invocation entry')
                            stack.extend(reversed(list(ast.iter_child_nodes(node))))
                            continue
                        if(producer.role not in {'direct_function','direct_method'}or node.keywords
                                or any(isinstance(arg,ast.Starred)for arg in node.args)):
                            raise Unproved('implicit/finite callback calls need a typed continuation invocation descriptor')
                        callee=producer.callee
                        if callee is None:raise Unproved('the source invocation has no canonical native target')
                        if plan is self.model.module:
                            statement=node
                            while id(statement)not in {id(item)for item in self.model.tree.body}:
                                statement=self.parents.get(id(statement))
                                if statement is None:raise Unproved('module call has no original statement owner')
                            if self.model.tree.body.index(statement)<=last_definition:
                                raise Unproved('call-only definitions must precede all module source invocations')
                        if cell is None and producer.role=='direct_function':
                            from .native_frame_references import call_target
                            if call_target(self.model,plan,node)is not self.source(callee):
                                if plan is self.model.module:
                                    statement=node
                                    while id(statement)not in {id(item)for item in self.model.tree.body}:
                                        statement=self.parents.get(id(statement))
                                        if statement is None:raise Unproved('module call has no original statement owner')
                                    if self.model.tree.body.index(statement)<=last_definition:
                                        raise Unproved('a call-only definition is not initialized before module source calls')
                                self.static_callees.add((plan.index,id(node)))
                        if len(producer.argument_nodes)!=len(callee.runtime_parameters):raise Unproved('call binding errors keep their existing native path')
                        self.targets[plan.index,id(node)]=callee
                stack.extend(reversed(list(ast.iter_child_nodes(node))))
        self.plans={plan.index:plan for plan in region}
        nodes={id(node):node for node in self.model.iter_nodes()}
        for(caller,site),targets in self.model.call_edges_by_site.items():
            plan=self.invocations.plans.get(caller)
            if plan is None:continue
            if(caller,site)in self.invocations.producers:continue
            node=nodes.get(site)
            producer=self.invocations.describe(plan,node,targets)
            if any(target in self.plans for target in targets):
                raise Unproved('an implicit source producer has no typed transfer/resume rule')
            if not all(synchronous(self.model,self.invocations.plans[target])for target in targets):
                raise Unproved('an unmodeled source entry can reenter a continuation region')
        if not self.invocations.complete():raise Unproved('the source invocation producer ledger is incomplete')
        # Typed source blocks currently cover ordinary statements. Reject
        # unlowered producers before any source body is emitted.
        for plan in region:
            reason=control_reason(self,plan,self.targets,self.plans)
            if reason is not None:raise Unproved(reason)


def control_reason(registry,plan,targets,selected):
    """One positive control/place matrix shared by every typed region proof."""
    from .native_classes import shape
    allowed=(ast.Assign,ast.AnnAssign,ast.AugAssign,ast.Expr,ast.Return,ast.If,
             ast.For,ast.While,ast.Break,ast.Continue,ast.Pass,ast.Global,ast.Nonlocal,ast.Assert)
    for node in ast.walk(registry.source(plan).node):
        if registry.omitted(plan,node):continue
        if isinstance(node,ast.stmt)and node is not registry.source(plan).node and not isinstance(node,allowed):
            return ('an ordinary statement has no typed continuation control rule')
        if isinstance(node,ast.AugAssign)and not isinstance(node.target,ast.Name)and any((plan.index,id(part))in targets and targets[plan.index,id(part)].index in selected for part in ast.walk(node)if isinstance(part,ast.Call)):
            return ('augmented container places need a suspension-safe captured owner/index')
        if isinstance(node,ast.AugAssign)and any((plan.index,id(part))in targets
                and targets[plan.index,id(part)].index in selected for part in ast.walk(node.value)if isinstance(part,ast.Call)):
            previous=registry.model.augmented.get((plan.index,id(node)))
            if previous is None or shape(previous)not in SCALARS:
                return ('suspending inplace container mutation needs a captured native place')
        if isinstance(node,(ast.Assign,ast.AnnAssign,ast.AugAssign,ast.For,ast.comprehension)):
            assignment_targets=node.targets if isinstance(node,ast.Assign)else[node.target]
            if any(any((plan.index,id(part))in targets and targets[plan.index,id(part)].index in selected
                           for part in ast.walk(target)if isinstance(part,ast.Call))for target in assignment_targets):
                return ('a suspending assignment target needs a typed place descriptor')
        if isinstance(node,ast.expr)and any((plan.index,id(part))in targets
                and targets[plan.index,id(part)].index in selected for part in ast.walk(node)if isinstance(part,ast.Call)):
            if not isinstance(node,(ast.Call,ast.BinOp,ast.UnaryOp,ast.Subscript,ast.Tuple,ast.List,ast.IfExp,ast.BoolOp)):
                return ('this suspending expression has no typed evaluation-order rule')
            if isinstance(node,ast.Subscript)and isinstance(node.value,ast.Attribute):
                from .native_classes import InstanceType
                from .native_owned_class_lists import selected as owned_field
                receiver=registry.model.records.get((plan.index,id(node.value.value)))
                kind=None if receiver is None else shape(receiver)
                owner=registry.model.classes.get(kind.name)if isinstance(kind,InstanceType)else None
                name=registry.model.resolved_name(plan,node.value)
                if owner is not None and name in owner.fields and owned_field(registry.model,owner,list(owner.fields).index(name)):
                    return ('a suspending owned class-list read needs an owned place descriptor')
            if isinstance(node,ast.Subscript)and isinstance(node.slice,ast.Slice):
                return ('suspending slice bounds need a captured sequence-place rule')
        if isinstance(node,ast.Assert)and any((plan.index,id(part))in targets and targets[plan.index,id(part)].index in selected for part in ast.walk(node)if isinstance(part,ast.Call)):
            return ('suspending assert message/control needs explicit conditional blocks')
        if isinstance(node,ast.For):
            from .native_classes import domain
            cell=registry.model.records.get((plan.index,id(node.iter)))
            if cell is None or domain(shape(cell))not in {'list','tuple','range'}:
                return ('the builtin iterator cursor is not continuation-normalized')
    return None


class Builder:
    def __init__(self,registry,emitter):
        self.registry=registry;self.emitter=emitter;self.plan=emitter.plan
        self.blocks=[Block()];self.current=0;self.temps={};self.extra={};self.overrides={};self.loops=[]
        self.arguments=[]
        slot=emitter.slot;expression=emitter.expression
        def framed_slot(instance,name,kind):return 'frame.'+slot(name,kind)
        def captured(instance,node):
            return self.overrides[id(node)]if id(node)in self.overrides else expression(node)
        emitter.slot=MethodType(framed_slot,emitter);emitter.expression=MethodType(captured,emitter)
        emitter.typed_continuation_builder=self
        self.original_expression=expression
        from .native_classes import shape,Expression
        for index,name in enumerate(self.plan.runtime_parameters):
            kind=shape(self.plan.arguments[name]);stored=emitter.model.namespace.local_kind(self.plan,name)or kind
            place=emitter.slot(name,stored)[6:]
            self.arguments.append((place,emitter.coerce(Expression('argument_'+str(index),kind),stored,self.plan.node)))
        self.statements(self.registry.source(self.plan).node.body)
        if self.current is not None:
            self.end(('return','()')if shape(self.plan.result)=='none'else('invalid_return',))
        names={}
        for(name,kind),field in emitter.slots.items():
            if name in names and names[name]!=kind:raise Unproved('type-changing local clearing needs a physical frame-place rule')
            names[name]=kind

    def new(self):self.blocks.append(Block());return len(self.blocks)-1
    def emit(self,code):self.blocks[self.current].code.append(code)
    def end(self,value):self.blocks[self.current].end=value;self.current=None
    def read(self,temp):
        from .native_classes import Expression
        return Expression('frame.'+temp+'.as_ref().expect("native continuation value").clone()',self.temps[temp])
    def temp(self,kind):
        name='value_'+str(len(self.temps));self.temps[name]=kind;return name
    def save(self,value):
        name=self.temp(value.kind);self.emit('frame.'+name+'=Some('+value.code+');');return name
    def has_call(self,node):
        return any((self.plan.index,id(part))in self.registry.targets and self.registry.targets[self.plan.index,id(part)].index in self.registry.plans
                   for part in ast.walk(node)if isinstance(part,ast.Call))

    def condition(self,node):
        # Condition-only AST nodes need no value Cell of their own. Preserve
        # short-circuit truth flow without coercing an int operand to bool.
        if isinstance(node,ast.UnaryOp)and isinstance(node.op,ast.Not):
            return '!('+self.condition(node.operand)+')'
        if isinstance(node,ast.BoolOp):
            result=self.temp('bool');join=self.new()
            for index,value in enumerate(node.values):
                code=self.condition(value);self.emit('frame.'+result+'=Some('+code+');')
                if index+1<len(node.values):
                    onward=self.new();truth=self.read(result).code
                    self.end(('branch',truth,onward,join)if isinstance(node.op,ast.And)else('branch',truth,join,onward));self.current=onward
            self.end(('jump',join));self.current=join;return self.read(result).code
        return self.emitter.truth(self.read(self.expression(node)),node)

    def expression(self,node):
        if not self.has_call(node):return self.save(self.emitter.expression(node))
        from .native_classes import Expression
        if isinstance(node,ast.IfExp):
            test=self.condition(node.test);yes,no,join=self.new(),self.new(),self.new();result=self.temp(self.emitter.kind(node))
            self.end(('branch',test,yes,no))
            for branch,value in ((yes,node.body),(no,node.orelse)):
                self.current=branch;part=self.expression(value)
                self.emit('frame.'+result+'=Some('+self.emitter.coerce(self.read(part),self.temps[result],node)+');');self.end(('jump',join))
            self.current=join;return result
        if isinstance(node,ast.BoolOp):
            result=self.temp(self.emitter.kind(node));join=self.new()
            for index,value in enumerate(node.values):
                part=self.expression(value)
                self.emit('frame.'+result+'=Some('+self.emitter.coerce(self.read(part),self.temps[result],node)+');')
                if index+1<len(node.values):
                    onward=self.new();test=self.emitter.truth(self.read(part),value)
                    self.end(('branch',test,onward,join)if isinstance(node.op,ast.And)else('branch',test,join,onward));self.current=onward
            self.end(('jump',join));self.current=join;return result
        children=[]
        if isinstance(node,ast.BinOp):children=[node.left,node.right]
        elif isinstance(node,ast.UnaryOp):children=[node.operand]
        elif isinstance(node,ast.Subscript)and not isinstance(node.slice,ast.Slice):children=[node.value,node.slice]
        elif isinstance(node,(ast.Tuple,ast.List)):children=list(node.elts)
        elif isinstance(node,ast.Call):
            producer=self.registry.invocations.producers.get((self.plan.index,id(node)))
            if producer is not None and producer.role=='direct_method':
                # Plain immutable method binding is already certified. Retain
                # its original owned receiver before any explicit arguments.
                children.append(producer.receiver)
            elif(self.plan.index,id(node.func))in self.emitter.model.records:children.append(node.func)
            elif isinstance(node.func,ast.Attribute):children.append(node.func.value)
            children.extend(node.args);children.extend(item.value for item in node.keywords)
        else:raise Unproved('this suspending expression has no typed evaluation-order rule')
        values={id(child):self.read(self.expression(child))for child in children}
        target=self.registry.targets.get((self.plan.index,id(node)))if isinstance(node,ast.Call)else None
        if target is not None and target.index in self.registry.plans:
            destination=self.temp(self.emitter.kind(node));resume=self.new()
            capture=self.registry.captured.get((self.plan.index,id(node)))
            if capture is not None:
                from .native_captured_invocations import bind_definition
                from .native_callable_carriers import bind_payload
                site=Site(len(self.registry.sites),self.plan,target,node,(),destination,resume,True)
                self.registry.sites.append(site)
                provider=self.emitter.model.callable_cells
                positional=[values[id(arg)]for arg in node.args]
                keywords=[(keyword.arg,values[id(keyword.value)])for keyword in node.keywords]
                binding=bind_definition(self.emitter,node,capture.definition,positional,keywords)
                if binding.target is not target:
                    raise Unproved('the analyzed captured native body differs from its bound target')
                code=('{'+bind_payload(provider,capture.definition,values[id(node.func)].code)
                      +provider.call_context_setup(self.emitter,binding.source)
                      +'Ok(ClassNativeStep::Call_'+str(site.index)+'('+binding.frame_code()+'))}')
                self.emit(code);self.end(('raw',));self.current=resume
                return destination
            producer=self.registry.invocations.producers[self.plan.index,id(node)]
            site=Site(len(self.registry.sites),self.plan,target,node,tuple(values[id(arg)]for arg in producer.argument_nodes),destination,resume)
            self.registry.sites.append(site);self.end(('call',site));self.current=resume;return destination
        old=self.overrides;self.overrides={**old,**values}
        try:value=self.original_expression(node)
        finally:self.overrides=old
        return self.save(value)

    def statements(self,nodes):
        for node in nodes:
            if self.current is None:break
            if self.registry.omitted(self.plan,node):continue
            self.statement(node)

    def statement(self,node):
        from .native_classes import Expression,shape,domain
        if isinstance(node,(ast.Pass,ast.Global,ast.Nonlocal)):return
        if isinstance(node,(ast.Assign,ast.AnnAssign,ast.AugAssign,ast.Expr,ast.Assert))and not self.has_call(node):
            # Reuse complete established statement semantics for atomic native
            # regions: e.g. list *= mutates in place, map unpack is a fused
            # parser, and annotation-only targets still evaluate their inputs.
            self.emit(self.emitter.statement(node));return
        if isinstance(node,ast.Expr):
            if not(isinstance(node.value,ast.Constant)and type(node.value.value)is str):self.expression(node.value)
            return
        if isinstance(node,(ast.Assign,ast.AnnAssign)):
            if node.value is None:
                from .native_annotations import target_inputs
                for value in target_inputs(node.target):self.expression(value)
                return
            value=self.read(self.expression(node.value))
            for target in node.targets if isinstance(node,ast.Assign)else[node.target]:self.emit(self.emitter.assign(target,value))
            return
        if isinstance(node,ast.AugAssign):
            before,reference=self.emitter.reference(node.target)
            self.emit(before);old=self.save(self.emitter.load_reference(reference,node.target,shape(self.emitter.model.augmented[self.plan.index,id(node)])))
            right=self.read(self.expression(node.value));value=self.emitter.binary(node.op,self.read(old),right,node,self.emitter.kind(node.target))
            self.emit(self.emitter.store_reference(reference,value,node.target));return
        if isinstance(node,ast.Return):
            value=Expression('()','none')if node.value is None else self.read(self.expression(node.value))
            self.end(('return',self.emitter.coerce(value,shape(self.plan.result),node)));return
        if isinstance(node,ast.If):
            test=self.condition(node.test);yes,no,join=self.new(),self.new(),self.new()
            self.end(('branch',test,yes,no))
            for branch,body in ((yes,node.body),(no,node.orelse)):
                self.current=branch;self.statements(body)
                if self.current is not None:self.end(('jump',join))
            self.current=join;return
        if isinstance(node,ast.While):
            head,body,otherwise,after=self.new(),self.new(),self.new(),self.new();self.end(('jump',head));self.current=head
            test=self.condition(node.test);self.end(('branch',test,body,otherwise))
            self.loops.append((head,after));self.current=body;self.statements(node.body);self.loops.pop()
            if self.current is not None:self.end(('jump',head))
            self.current=otherwise;self.statements(node.orelse)
            if self.current is not None:self.end(('jump',after))
            self.current=after;return
        if isinstance(node,ast.For):
            source_name=self.expression(node.iter);source=self.read(source_name);kind=source.kind;index=None;iterator=None
            if domain(kind)!='range':
                index='index_'+str(len(self.extra));self.extra[index]=('usize','0');self.emit('frame.'+index+'=0;')
            if domain(kind)=='range':
                iterator='range_'+str(len(self.extra));self.extra[iterator]=('Option<NativeRange>','None');self.emit('frame.'+iterator+'=Some(('+source.code+').iter());')
            head,body,otherwise,after=self.new(),self.new(),self.new(),self.new();self.end(('jump',head));self.current=head
            if domain(kind)=='list':pull='{let source='+source.code+';let item=source.borrow().get(frame.'+index+').cloned();item}';item_kind=kind.element
            elif domain(kind)=='tuple':
                item_kind=self.emitter.kind(node.target)
                pull='match frame.'+index+'{'+','.join(str(i)+'=>Some('+self.emitter.coerce(Expression('('+source.code+').'+str(i)+'.clone()',part),item_kind,node)+')'for i,part in enumerate(kind.fields))+',_=>None}'
            elif domain(kind)=='range':pull='frame.'+iterator+'.as_mut().unwrap().next()';item_kind='int'
            else:raise Unproved('this iterator cursor is not an owned builtin list/tuple/range continuation')
            item=self.emitter.fresh();code='let '+item+'='+pull+';'
            code+='if let Some(value)='+item+'{'
            if index is not None:code+='frame.'+index+'='+self.emitter.at('frame.'+index+'.checked_add(1).ok_or_else(||"OverflowError: list iterator index overflow".to_owned())',node)+';'
            code+=self.emitter.assign(node.target,Expression('value',item_kind))+'Ok(ClassNativeStep::Jump_'+str(self.plan.index)+'(ClassNativePc_'+str(self.plan.index)+'::B'+str(body)+'))}else{Ok(ClassNativeStep::Jump_'+str(self.plan.index)+'(ClassNativePc_'+str(self.plan.index)+'::B'+str(otherwise)+'))}'
            self.emit(code);self.end(('raw',))
            self.loops.append((head,after));self.current=body;self.statements(node.body);self.loops.pop()
            if self.current is not None:self.end(('jump',head))
            self.current=otherwise;self.statements(node.orelse)
            if self.current is not None:self.end(('jump',after))
            self.current=after;return
        if isinstance(node,(ast.Break,ast.Continue)):
            self.end(('jump',self.loops[-1][0 if isinstance(node,ast.Continue)else 1]));return
        if isinstance(node,ast.Assert)and not self.has_call(node):self.emit(self.emitter.statement(node));return
        raise Unproved('ordinary control has no typed continuation block')

    def frame(self):
        from .native_classes import shape
        e=self.emitter;i=self.plan.index
        fields={name:'Option<'+e.rust_type(kind)+'>'for(_,kind),name in e.slots.items()}
        fields.update((name,'Option<'+e.rust_type(kind)+'>')for name,kind in self.temps.items());fields.update((name,kind)for name,(kind,_)in self.extra.items())
        params=','.join('argument_'+str(n)+':'+e.rust_type(kind)for n,kind in enumerate(shape(self.plan.arguments[name])for name in self.plan.runtime_parameters))
        initial={name:'None'for name in fields};initial.update((name,value)for name,(_,value)in self.extra.items());initial.update((name,'Some('+value+')')for name,value in self.arguments)
        body='struct ClassNativeFrame_'+str(i)+'{scope:ClassScope,'+','.join(name+':'+kind for name,kind in fields.items())+'}'
        body+='impl ClassNativeFrame_'+str(i)+'{fn new(scope:ClassScope'+(','+params if params else'')+')->Self{Self{scope,'+','.join(name+':'+value for name,value in initial.items())+'}}}'
        body+='enum ClassNativePc_'+str(i)+'{'+','.join('B'+str(n)for n in range(len(self.blocks)))+'}'
        return body

    def body(self):
        i=self.plan.index;arms=[]
        for index,block in enumerate(self.blocks):
            end=block.end or('unreachable',);tag=end[0]
            if tag=='jump':tail='Ok(ClassNativeStep::Jump_'+str(i)+'(ClassNativePc_'+str(i)+'::B'+str(end[1])+'))'
            elif tag=='branch':tail='Ok(ClassNativeStep::Jump_'+str(i)+'(if '+end[1]+'{ClassNativePc_'+str(i)+'::B'+str(end[2])+'}else{ClassNativePc_'+str(i)+'::B'+str(end[3])+'}))'
            elif tag=='call':tail='Ok(ClassNativeStep::Call_'+str(end[1].index)+')'
            elif tag=='return':tail='Ok(ClassNativeStep::Return_'+str(i)+'('+end[1]+'))'
            elif tag=='invalid_return':tail='Err(native_error("RuntimeError: invalid compiled return".into(),'+str(getattr(self.plan.node,'lineno',1))+','+self.emitter.location_code()+'))'
            elif tag=='unreachable':tail='unreachable!("native unreachable block")'
            else:tail=''
            arms.append('ClassNativePc_'+str(i)+'::B'+str(index)+'=>{'+''.join(block.code)+tail+'}')
        return 'match pc{'+','.join(arms)+'}'


def prepare(model):model.typed_continuations=Registry(model)


def selected(model,plan):return plan is not None and plan.index in getattr(getattr(model,'typed_continuations',None),'plans',())
def entry_result(model,plan):return plan is not None and plan.index in getattr(getattr(model,'typed_continuations',None),'result_entries',())


def assert_source_call_lowered(emitter,callee):
    if getattr(emitter,'typed_continuation_builder',None)is not None and selected(emitter.model,callee):
        raise AssertionError('a typed source block attempted to reenter a selected entry wrapper')


def validate_transfers(model,registry):
    expected={(caller,site,target)for(caller,site),targets in model.call_edges_by_site.items()
              if caller in registry.plans for target in targets if target in registry.plans}
    actual={(site.caller.index,id(site.node),site.callee.index)for site in registry.sites}
    if expected!=actual:
        raise AssertionError(('a selected source activation has no consumed typed transfer',
                              expected-actual,actual-expected))


def generate(emitter):
    registry=getattr(emitter.model,'typed_continuations',None)
    if registry is None or not selected(emitter.model,emitter.plan):return None
    from .native_classes import shape
    builder=Builder(registry,emitter);registry.builders[emitter.plan.index]=builder;i=emitter.plan.index
    params=','.join('class_argument_'+str(n)+':'+emitter.rust_type(shape(emitter.plan.arguments[name]))for n,name in enumerate(emitter.plan.runtime_parameters))
    args=','.join('class_argument_'+str(n)for n in range(len(emitter.plan.runtime_parameters)))
    return ('fn '+emitter.function_name(emitter.plan)+'(class_scope:ClassScope'+(','+params if params else'')+')->ClassResult<'+emitter.rust_type(shape(emitter.plan.result))+'> {'
            'match class_native_region(ClassNativeState::F_'+str(i)+'(ClassNativeFrame_'+str(i)+'::new(class_scope'+(','+args if args else'')+'),ClassNativePc_'+str(i)+'::B0))?{ClassNativeReturn::F_'+str(i)+'(value)=>Ok(value),_=>unreachable!("native root return")}}')


def runtime(model):
    registry=getattr(model,'typed_continuations',None)
    if registry is None or not registry.plans:return ''
    from .native_classes import shape
    validate_transfers(model,registry)
    builders=registry.builders;result=[builder.frame()for builder in builders.values()]
    result.append('enum ClassNativeState{'+','.join('F_'+str(i)+'(ClassNativeFrame_'+str(i)+',ClassNativePc_'+str(i)+')'for i in builders)+'}')
    result.append('enum ClassNativeReturn{'+','.join('F_'+str(i)+'('+b.emitter.rust_type(shape(b.plan.result))+')'for i,b in builders.items())+'}')
    result.append('enum ClassNativeContinuation{'+','.join('Site_'+str(site.index)+'{frame:ClassNativeFrame_'+str(site.caller.index)+'}'for site in registry.sites)+'}')
    result.append('enum ClassNativeStep{'+','.join(['Jump_'+str(i)+'(ClassNativePc_'+str(i)+'),Return_'+str(i)+'('+b.emitter.rust_type(shape(b.plan.result))+')'for i,b in builders.items()]+['Call_'+str(site.index)+('(ClassNativeFrame_'+str(site.callee.index)+')'if site.owned_child else'')for site in registry.sites])+'}')
    unwinds=','.join('ClassNativeContinuation::Site_'+str(site.index)+'{..}=>{error.frames.push(('+str(site.node.lineno)+','+builders[site.caller.index].emitter.location_code()+'));}'for site in registry.sites)
    result.append('fn class_native_unwind(stack:&mut Vec<ClassNativeContinuation>,class_scope:&ClassScope,mut error:NativeError)->NativeError{'
                  'while let Some(caller)=stack.pop(){class_scope.control.borrow_mut().depth-=1;match caller{'+unwinds+'}}error}')
    state_arms=[]
    for i,b in builders.items():
        e=b.emitter;steps=[]
        steps.append('ClassNativeStep::Jump_'+str(i)+'(pc)=>{state=ClassNativeState::F_'+str(i)+'(frame,pc);continue;}')
        returns=[]
        for site in registry.sites:
            if site.callee.index!=i:continue
            caller=builders[site.caller.index]
            from .native_classes import Expression
            converted=caller.emitter.coerce(Expression('value',shape(b.plan.result)),caller.temps[site.destination],site.node)
            returns.append('Some(ClassNativeContinuation::Site_'+str(site.index)+'{mut frame})=>{frame.scope.control.borrow_mut().depth-=1;frame.'+site.destination+'=Some('+converted+');state=ClassNativeState::F_'+str(site.caller.index)+'(frame,ClassNativePc_'+str(site.caller.index)+'::B'+str(site.resume)+');continue;}')
        steps.append('ClassNativeStep::Return_'+str(i)+'(value)=>{drop(frame);match stack.pop(){'+(''.join(value+','for value in returns))+'None=>return Ok(ClassNativeReturn::F_'+str(i)+'(value)),_=>unreachable!("native return site")}}')
        for site in registry.sites:
            if site.caller.index!=i:continue
            callee=builders[site.callee.index];args=[e.coerce(value,shape(callee.plan.arguments[name]),site.node)for name,value in zip(callee.plan.runtime_parameters,site.arguments)]
            error='native_error("RecursionError: maximum recursion depth exceeded".into(),'+str(site.node.lineno)+','+e.location_code()+')'
            head='ClassNativeStep::Call_'+str(site.index)+('(child)'if site.owned_child else'')
            child=''if site.owned_child else('let child=ClassNativeFrame_'+str(site.callee.index)+'::new(class_scope.clone()'+(','+','.join(args)if args else'')+');')
            steps.append(head+'=>{if class_scope.control.borrow().depth>=class_scope.control.borrow().limit{let error='+error+';'+unwind_code()+'}'
                         'if stack.try_reserve(1).is_err(){let error=native_error("MemoryError: cannot allocate native call frame".into(),'+str(site.node.lineno)+','+e.location_code()+');'+unwind_code()+'}'
                         +child+'class_scope.control.borrow_mut().depth+=1;stack.push(ClassNativeContinuation::Site_'+str(site.index)+'{frame});state=ClassNativeState::F_'+str(site.callee.index)+'(child,ClassNativePc_'+str(site.callee.index)+'::B0);continue;}')
        state_arms.append('ClassNativeState::F_'+str(i)+'(mut frame,pc)=>{let class_scope=frame.scope.clone();let outcome:ClassResult<ClassNativeStep>=(||{'+b.body()+'})();match outcome{Err(error)=>{'+unwind_code()+'},Ok(step)=>match step{'+','.join(steps)+',_=>unreachable!("native step owner")}}}')
    body=','.join(state_arms)
    imports='use std::fmt::Write as _;'if 'write!'in body else''
    result.append('fn class_native_region(mut state:ClassNativeState)->ClassResult<ClassNativeReturn>{'+imports+'let mut stack:Vec<ClassNativeContinuation>=Vec::new();loop{match state{'+body+'}}}')
    return '\n'.join(result)


def unwind_code():
    return 'return Err(class_native_unwind(&mut stack,&class_scope,error));'
