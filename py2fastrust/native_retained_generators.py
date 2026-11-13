"""Owned typed frames for original retained generator-expression nodes."""
import ast
from dataclasses import dataclass

from .native_classes import FunctionPlan


class ExpressionFrame(FunctionPlan):
    @property
    def scope(self):return '<genexpr>'


@dataclass
class Expression:
    iterator:object
    parent:object
    frame:object
    node:object
    scope:int
    outer:object=None
    semantic:object=None
    creation:object=None
    body:object=None
    inners:tuple=()
    emitted:bool=False
    helper:str|None=None


def registry(model):
    value=getattr(model,'retained_generators',None)
    if value is None:value=model.retained_generators=Registry(model)
    return value


def requires_frames(unit,analysis):
    """Keep existing immediate collectors on their original physical path."""
    from .native_immediate_generators import CONSUMERS
    from .references import BuiltinIdentity
    from .native_module_calls import BuiltinRef
    from .native_itertools import ItertoolsAdapter
    from .native_functools_reduce import FunctoolsAdapter
    from .native_frame_heapq import HeapAdapter
    from .native_class_counters import CollectionsAdapter
    adapters={'itertools':ItertoolsAdapter,'functools':FunctoolsAdapter,
              'heapq':HeapAdapter,'collections':CollectionsAdapter}
    def eager(identity,position,keyword):
        if isinstance(identity,BuiltinIdentity):
            return keyword is None and position==0 and identity.name in CONSUMERS
        if not isinstance(identity,BuiltinRef):return False
        adapter=adapters.get(identity.module)
        if adapter is None or identity.name not in adapter.NAMES:return False
        if keyword is not None:
            return keyword in getattr(adapter,'EAGER_KEYWORDS',{}).get(identity.name,())
        capabilities=getattr(adapter,'EAGER_ARGUMENTS',{})
        if identity.name not in capabilities or position is None:return False
        positions=capabilities[identity.name]
        return positions is None or position in positions
    def proved(identities,position,keyword=None):
        return identities and all(not identity.unknown and not identity.unbound and identity.alternatives
            and all(eager(part,position,keyword)for part in identity.alternatives)
            for identity in identities)
    nodes={unit.ordinal(node):node for node in ast.walk(unit.tree)}
    parents={id(child):node for node in nodes.values()for child in ast.iter_child_nodes(node)}
    reached={site for facts in analysis.scopes.values()for site in set(facts.expressions)|set(facts.values)}
    calls={}
    for facts in analysis.scopes.values():
        for site,call in facts.calls.items():calls.setdefault(site,[]).append(call.identity)
    for ordinal,node in nodes.items():
        if not isinstance(node,ast.GeneratorExp)or ordinal not in reached:continue
        parent=parents.get(id(node))
        if isinstance(parent,ast.Assign)and parent.value is node:
            if all(isinstance(target,ast.Subscript)and isinstance(target.slice,ast.Slice)for target in parent.targets):continue
            if len(parent.targets)==1 and isinstance(parent.targets[0],(ast.Tuple,ast.List))and not any(isinstance(child,ast.Starred)for child in parent.targets[0].elts):continue
        if isinstance(parent,ast.Starred)and isinstance(parents.get(id(parent)),ast.Call):continue
        if isinstance(parent,ast.Call)and node in parent.args:
            identities=calls.get(unit.ordinal(parent),())
            position=parent.args.index(node)
            if any(isinstance(part,ast.Starred)for part in parent.args[:position]):position=None
            if proved(identities,position):continue
        # Native member consumers retain their established eager capabilities.
        if isinstance(parent,ast.keyword):
            call=parents.get(id(parent));identities=calls.get(unit.ordinal(call),())if isinstance(call,ast.Call)else()
            if parent.arg is not None and proved(identities,None,parent.arg):continue
        return True
    return False


class Registry:
    def __init__(self,model):self.model=model;self.records=[];self.sites={};self.methods={}

    def analyze(self,parent,node,environment):
        from .native_classes import Cell,Environment,ClassUnsupported
        from .native_types import EMPTY
        if any(clause.is_async for clause in node.generators):
            raise ClassUnsupported(node,'async generator-expression iteration requires asynchronous Python iterator protocols; native retained expressions currently use synchronous for clauses',proof='retained generator-expression async iteration')
        if len(node.generators)>1:
            assignment=next((child for child in ast.walk(node)if isinstance(child,ast.NamedExpr)),None)
            if assignment is not None:
                raise ClassUnsupported(assignment,'assignment expressions inside multi-clause retained generators need a suspension-aware enclosing-binding effect proof; that additional walrus adapter is not implemented',proof='retained nested-generator assignment-expression effects')
        if parent.class_body is not None:
            raise ClassUnsupported(node,'a retained generator expression created in a class namespace requires class-body closure and global lookup separation; that capture context is not implemented',proof='retained generator-expression class namespace capture')
        key=parent.index,id(node)
        record=self.sites.get(key)
        if record is None:
            scope=self.model.unit.scope_for(node).ordinal
            metadata=self.model.unit.scopes[scope]
            frame=ExpressionFrame(node,len(self.model.plans),owner=parent.owner,parameters=['.0'],declared={symbol.name for symbol in metadata.symbols if symbol.has('local')or symbol.has('parameter')},reachable=False,source_unit=parent.source_unit,module_name=parent.module_name)
            frame._native_retained_expression=True
            iterator=self.model.iterators._record(parent,node,'retained_generator_expression')
            from .native_iterator_hints import ABSENT
            iterator.hint_protocol=ABSENT
            iterator.element=Cell(EMPTY);iterator.adapter=ADAPTER
            record=Expression(iterator,parent,frame,node,scope)
            iterator.expression=record;iterator.expression_registry=self;frame.retained_expression=record
            frame.result=iterator.element
            self.model.plans.append(frame)
            self.sites[key]=record;self.records.append(record)
            lexical=self.model.lexical
            known_scopes=set(lexical.scope_plans)
            if not self.model.lambda_cells.register_scope(lexical,metadata.parent):
                raise ClassUnsupported(node,'the retained generator expression has no compiled official enclosing scope for its lexical cells',proof='retained generator-expression lexical ancestry')
            lexical.scope_plans[scope]=frame
            lexical.parents[scope]=metadata.parent
            if scope in lexical.environments:lexical.environments[scope].plan=frame
            fresh_scopes=(set(lexical.scope_plans)-known_scopes)|{scope}
            for binding in self.model.iter_bindings():
                if binding.owner in fresh_scopes and lexical.execution_scope(binding.scope)!=binding.owner:
                    lexical.environment(binding.owner).fields.setdefault(binding.name,Cell())
            for capture in list(lexical.environments.values()):
                parent_scope=capture.parent
                while parent_scope is not None and not self.model.module_owner(parent_scope):
                    capture_parent=lexical.environment(parent_scope)
                    parent_scope=capture_parent.parent
        first=self.model.expression(parent,node.generators[0].iter,environment)
        record.outer=self.model.iterators.source(parent,node,first,('retained_outer',record.iterator.index),environment=environment)
        record.frame.arguments['.0']=self.model.cell_for_kind(record.outer)
        record.creation=Environment(environment)
        from .native_class_comprehensions import _normalizer
        record.semantic=_normalizer(self.model,parent,environment).comprehension(node)
        return self.model.cell(parent,node,record.iterator.kind)

    def demand(self,caller,node,record,environment,active):
        from .native_classes import ClassUnsupported
        expression=record.expression;frame=expression.frame
        if record.index in active:raise ClassUnsupported(node,'retained generator-expression cursor ownership/pull recurses into its own family; a cycle-safe resumable iterator graph is not implemented',proof='finite retained generator-expression ownership')
        record.demands[caller.index,id(node)]=True
        self.model.activate_frame(caller,node,frame,environment)
        self.model.namespace.call_effects(caller,frame,environment)
        return record.element

    def analyze_body(self,frame,environment):
        from .native_classes import Cell,Environment
        expression=frame.retained_expression;record=expression.iterator
        inside=Environment(environment)
        from .native_class_comprehensions import analyze
        def element(values,semantic):
            self.model.iterators._contribute(record.element,self.model.expression(frame,semantic.element,values),semantic.element)
            return record.element
        def retain_source(index,source,value,values):
            if index==0:return value
            kind=self.model.iterators.source(frame,source.node,value,('retained_inner',index),environment=values)
            inners=list(expression.inners)
            while len(inners)<index:inners.append(None)
            inners[index-1]=kind;expression.inners=tuple(inners)
            return self.model.cell_for_kind(kind)
        adapt=retain_source if len(expression.node.generators)>1 else None
        analyze(self.model,frame,expression.node,inside,contribute=element,first_value=self.model.cell_for_kind(expression.outer),semantic=expression.semantic,adapt_source=adapt)
        expression.body=self.model.comprehensions[frame.index,id(expression.node)]
        self.model.exceptions.require(expression.node)
        return None

    def synchronous(self,expression):
        from .native_classes import ClassUnsupported
        if expression.frame.index not in self.model.synchronous_calls:
            raise ClassUnsupported(expression.node,'this retained generator-expression body or outer cursor invokes a recursive/asynchronous source callback; a resumable recursive call continuation for this expression frame is not implemented',proof='bounded native retained generator-expression body calls')
        return True

    def construct(self,emitter,node):
        from .native_classes import Expression
        expression=self.sites[emitter.plan.index,id(node)]
        expression.emitted=True;expression.iterator.emitted=True
        setup,first=emitter.capture(emitter.expression(node.generators[0].iter))
        outer=self.model.iterators.construct(emitter,node,first,kind=expression.outer)
        before,outer=emitter.capture(outer);setup+=before
        extra,fields=self.capture(emitter,expression);setup+=extra
        initial=['scope:class_scope.clone()','outer:'+outer.code,*fields]
        if expression.body is not None:
            initial.extend('target_'+str(index)+':None'for index,_ in enumerate(self.bindings(expression)))
            initial.extend('inner_'+str(index)+':None'for index,_ in enumerate(expression.inners,1))
        expression.helper=self.generate(emitter,expression)
        state='ClassIteratorState_'+str(expression.iterator.index)
        frame='ClassRetainedExpressionFrame_'+str(expression.iterator.index)
        return Expression('{'+setup+'Rc::new(RefCell::new('+state+'{running:false,frame:Some('+frame+'{'+','.join(initial)+'})}))}',expression.iterator.kind)

    def capture(self,emitter,expression):
        lexical=self.model.lexical;scope=expression.scope;fields=[];setup=''
        own=lexical.environments.get(scope)if expression.body is not None else None
        if own is not None:
            before,context=self.model.lambda_cells.comprehension_initialize(emitter,expression.node)
            setup+=before;fields.append('environment:'+context[1])
            lexical.active.add(scope)
        else:
            parent=lexical.parent_scope(expression.frame)
            if parent is not None and parent in lexical.environments:
                fields.append('parent:('+lexical.expression_environment(emitter,parent)+').clone()')
        return setup,fields

    def bindings(self,expression):
        from .native_classes import shape
        result=[]
        for clause in expression.node.generators:
            for target in ast.walk(clause.target):
                if not isinstance(target,ast.Name)or self.model.lexical.field_for(target)is not None:continue
                name=self.model.resolved_name(expression.frame,target)
                cell=self.model.records[expression.frame.index,id(target)]
                entry=name,shape(cell)
                if entry not in result:result.append(entry)
        return result

    def generate(self,parent_emitter,expression):
        from .native_classes import Expression,shape
        from .native_class_comprehensions import _assign
        frame=expression.frame;scope=expression.scope;i=str(expression.iterator.index)
        emitter=type(parent_emitter)(self.model,frame)
        emitter.logical_scope='<genexpr>';emitter.logical_binding_scope=scope
        emitter.primitive_parameters={};emitter.readonly_owned_parameters={}
        emitter.owned_local_lists={};emitter.owned_matrices={};emitter.record_places={}
        fields=['scope:ClassScope','outer:'+emitter.rust_type(expression.outer)]
        lexical=self.model.lexical;own=lexical.environments.get(scope)if expression.body is not None else None
        if own is not None:
            fields.append('environment:Rc<'+lexical.environment_type(scope)+'>')
            emitter.comprehension_environments={scope:'frame.environment'}
            if own.parent:emitter.lexical_environment_override='frame.environment.parent.clone()'
        else:
            parent=lexical.parent_scope(frame)
            if parent is not None and parent in lexical.environments:
                fields.append('parent:Rc<'+lexical.environment_type(parent)+'>')
                emitter.lexical_environment_override='frame.parent.clone()'
        body=''
        if expression.body is not None:
            self.synchronous(expression)
            bindings={}
            for index,(name,kind)in enumerate(self.bindings(expression)):
                fields.append('target_'+str(index)+':Option<'+emitter.rust_type(kind)+'>')
                bindings[name,kind]='frame.target_'+str(index)
            emitter.comprehension_bindings=[(set(expression.body.bindings),bindings)]
            if len(expression.node.generators)>1:
                return self.generate_nested(emitter,expression,fields,bindings)
            value=self.model.iterators.pull(emitter,expression.node,Expression('frame.outer.clone()',expression.outer))
            item=emitter.fresh()
            body='loop{let Some('+item+')=('+value.code+')else{return Ok(None);};'+_assign(emitter,expression.node.generators[0].target,Expression(item,value.kind),bindings)
            for condition in expression.node.generators[0].ifs:
                before,test=emitter.capture(emitter.condition(condition));body+=before+'if !('+emitter.truth(test,condition)+'){continue;}'
            result=emitter.expression(expression.node.elt)
            body+='return Ok(Some('+emitter.coerce(result,shape(expression.iterator.element),expression.node.elt)+'));}'
        layout='struct ClassRetainedExpressionFrame_'+i+'{'+','.join(fields)+'}'
        if not body:return layout
        return layout+'\nfn class_retained_expression_resume_'+i+'(frame:&mut ClassRetainedExpressionFrame_'+i+')->ClassResult<Option<'+emitter.rust_type(shape(expression.iterator.element))+'>>{let class_scope=frame.scope.clone();'+body+'}'

    def generate_nested(self,emitter,expression,fields,bindings):
        from .native_classes import Expression,shape,ClassUnsupported
        from .native_class_comprehensions import _assign
        if len(expression.inners)!=len(expression.node.generators)-1 or any(kind is None for kind in expression.inners):
            raise ClassUnsupported(expression.node,'a nested retained generator clause has no solved registered cursor layout',proof='complete retained inner-cursor state')
        self.validate_nested_ownership(expression)
        i=str(expression.iterator.index)
        frame='ClassRetainedExpressionFrame_'+i
        result='ClassResult<Option<'+emitter.rust_type(shape(expression.iterator.element))+'>>'
        fields.extend('inner_'+str(index)+':Option<'+emitter.rust_type(kind)+'>'for index,kind in enumerate(expression.inners,1))
        helpers=[]
        for index,clause in enumerate(expression.node.generators):
            if index==0:
                name='class_retained_expression_resume_'+i
                cursor=Expression('frame.outer.clone()',expression.outer)
            else:
                name='class_retained_expression_clause_'+i+'_'+str(index)
                cursor=Expression('frame.inner_'+str(index)+'.as_ref().expect("active retained inner cursor").clone()',expression.inners[index-1])
            body='loop{'
            if index<len(expression.inners):
                child=str(index+1)
                body+=('if frame.inner_'+child+'.is_some(){'
                       'if let Some(value)=class_retained_expression_clause_'+i+'_'+child+'(frame)?{return Ok(Some(value));}'
                       'frame.inner_'+child+'=None;}')
            source_node=expression.node if index==0 else clause.iter
            value=self.model.iterators.pull(emitter,source_node,cursor)
            item=emitter.fresh()
            body+='let Some('+item+')=('+value.code+')else{return Ok(None);};'
            body+=_assign(emitter,clause.target,Expression(item,value.kind),bindings)
            for condition in clause.ifs:
                before,test=emitter.capture(emitter.condition(condition))
                body+=before+'if !('+emitter.truth(test,condition)+'){continue;}'
            if index<len(expression.inners):
                next_clause=expression.node.generators[index+1]
                before,source=emitter.capture(emitter.expression(next_clause.iter))
                constructed=self.model.iterators.construct(emitter,next_clause.iter,source,kind=expression.inners[index])
                body+=before+'frame.inner_'+str(index+1)+'=Some('+constructed.code+');'
            else:
                yielded=emitter.expression(expression.node.elt)
                body+='return Ok(Some('+emitter.coerce(yielded,shape(expression.iterator.element),expression.node.elt)+'));'
            body+='}'
            helpers.append('fn '+name+'(frame:&mut '+frame+')->'+result+'{let class_scope=frame.scope.clone();'+body+'}')
        return 'struct '+frame+'{'+','.join(fields)+'}\n'+'\n'.join(helpers)

    def validate_nested_ownership(self,expression):
        """An Rc ownership proof cannot supply a missing collector root facet."""
        from .native_classes import ClassUnsupported,InstanceType,shape
        from .native_types import ListType,TupleSequenceType,TupleType,UnionType,NullableType,MaybeType
        seen=set();environments=set()
        def environment(scope):
            if scope in environments:return
            environments.add(scope)
            captured=self.model.lexical.environments.get(scope)
            if captured is None:return
            for cell in (*captured.fields.values(),*captured.defaults.values()):check(shape(cell))
            if captured.parent is not None:environment(captured.parent)
        def check(kind):
            if kind is None:
                raise ClassUnsupported(expression.node,'a retained inner cursor or target payload remains unresolved; its suspended ownership layout is not established',proof='resolved retained nested-generator payload')
            if kind in seen:return
            seen.add(kind)
            if isinstance(kind,InstanceType)and getattr(self.model,'gc_classes',()):
                raise ClassUnsupported(expression.node,'nested retained generators can retain a class instance while the class collector is active; traced roots for these suspended inner cursor and target fields are not implemented',types=(('retained instance',kind),),proof='traced nested-generator class roots')
            if isinstance(kind,(ListType,TupleSequenceType)):check(kind.element)
            elif isinstance(kind,TupleType):
                for part in kind.fields:check(part)
            elif isinstance(kind,UnionType):
                for part in kind.alternatives:check(part)
            elif isinstance(kind,(NullableType,MaybeType)):check(kind.value)
            for owned in getattr(kind,'_native_owned_kinds',()):check(owned)
            if getattr(kind,'_native_function_reference',False):
                for definition in kind.definitions:
                    target=self.model.lexical.plans.get(definition)
                    if target is None:
                        raise ClassUnsupported(expression.node,'a retained nested-generator callable has no registered official lexical plan for its suspended environment',proof='registered retained callable lexical owner')
                    parent=self.model.lexical.parent_scope(target)
                    if parent is not None:environment(parent)
        for kind in(expression.outer,*expression.inners,shape(expression.iterator.element),*(kind for _,kind in self.bindings(expression))):check(kind)
        environment(expression.scope)

    def runtime(self):return '\n'.join(record.helper for record in self.records if record.emitted and record.helper is not None)


class Adapter:
    def owned(self,record):
        from .native_classes import shape
        expression=record.expression
        values=(expression.outer,shape(record.element))
        if len(expression.node.generators)>1:
            values+=expression.inners
            if expression.body is not None:values+=tuple(kind for _,kind in record.expression_registry.bindings(expression))
        return tuple(value for value in values if value is not None)
    def demand(self,iterators,plan,node,record,environment,active):return registry(iterators.model).demand(plan,node,record,environment,active)
    def may_call(self,iterators,record,seen):return True
    def fields(self,emitter,record):return 'frame:Option<ClassRetainedExpressionFrame_'+str(record.index)+'>,running:bool'
    def lifetime_edges(self,model,record,edges,targets):
        expression=record.expression;lexical=model.lexical;scope=expression.scope
        parent=scope if expression.body is not None and scope in lexical.environments else lexical.parent_scope(expression.frame)
        if parent is not None and parent in lexical.environments:edges['iterator',record.index].add(('environment',parent))
    def pull(self,iterators,emitter,node,value,active):
        from .native_classes import Expression,shape
        from .native_iterator_stop_policy import callback_call
        record=value.kind.record;expression=record.expression
        registry(iterators.model).synchronous(expression)
        handle,state,frame,outcome=(emitter.fresh()for _ in range(4))
        error=emitter.at('Err::<(),String>("ValueError: generator already executing".to_owned())',node)
        resumed=callback_call(emitter,'class_retained_expression_resume_'+str(record.index)+'(frame)',expression.frame,node)
        called='(||{Ok::<Option<'+emitter.rust_type(shape(record.element))+'>,NativeError>('+resumed+')})()'
        code=('{let '+handle+'=('+value.code+').clone();let mut '+frame+'={let mut '+state+'='+handle+'.borrow_mut();if '+state+'.running{'+error+';}'+state+'.running=true;'+state+'.frame.take()};'
              'let '+outcome+'=match '+frame+'.as_mut(){Some(frame)=>'+called+',None=>Ok(None)};'
              '{let mut '+state+'='+handle+'.borrow_mut();'+state+'.running=false;if matches!(&'+outcome+',Ok(Some(_)))||(matches!(&'+outcome+',Err(_))&&!'+emitter.iterator_callback_context+'){'+state+'.frame='+frame+';}}'
              +outcome+'.map_err(|error|{if class_exception_is_stop(&error){'+emitter.iterator_callback_context+'=false;class_exception_generator_stop(error,'+str(node.lineno)+','+emitter.location_code()+')}else{error}})?}')
        return Expression(code,shape(record.element))


ADAPTER=Adapter()


def runtime(model):
    value=getattr(model,'retained_generators',None)
    return ''if value is None else value.runtime()


def analyze_method(model,plan,node,owner,arguments,keywords,environment):
    from .native_classes import shape,ClassUnsupported
    kind=shape(owner)
    if getattr(getattr(kind,'record',None),'operation',None)!='retained_generator_expression':return None
    name=node.func.attr
    if name!='close':
        raise ClassUnsupported(node,'retained generator-expression '+name+'() requires an unimplemented generator method/injection protocol; ordinary iteration, next() and close() are implemented',proof='retained generator-expression '+name+' method')
    error=('TypeError: generator.close() takes no keyword arguments'if keywords else
           'TypeError: generator.close() takes no arguments ('+str(len(arguments))+' given)'if arguments else None)
    registry(model).methods[plan.index,id(node)]=error
    return model.cell(plan,node,'none')


def emit_method(emitter,node):
    value=getattr(emitter.model,'retained_generators',None)
    key=emitter.plan.index,id(node)
    if value is None or key not in value.methods:return None
    from .native_classes import Expression
    from .call_semantics import normalize_call
    from .native import _string
    setup,owner=emitter.capture(emitter.expression(node.func.value))
    for argument in normalize_call(node).evaluation_order:
        before,unused=emitter.capture(emitter.expression(argument.expression));setup+=before
    error=value.methods[key]
    if error:return Expression('{'+setup+emitter.at('Err::<(),String>('+_string(error)+'.to_owned())',node)+'}','none')
    state,frame=emitter.fresh(),emitter.fresh()
    running=emitter.at('Err::<(),String>("ValueError: generator already executing".to_owned())',node)
    code='let '+frame+'={let mut '+state+'='+owner.code+'.borrow_mut();if '+state+'.running{'+running+';}'+state+'.frame.take()};drop('+frame+');'
    return Expression('{'+setup+code+'}','none')
