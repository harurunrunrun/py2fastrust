"""Direct loop collectors for nonescaping original generator expressions."""
import ast
from contextlib import contextmanager
from dataclasses import dataclass,field

from .references import BuiltinIdentity
from .native_types import alternatives

CONSUMERS=frozenset({'sum','list','any','all','min','max','next','sorted'})


@dataclass(frozen=True)
class GeneratorType:
    index:int
    record:object=field(compare=False,hash=False,repr=False)
    _native_reference_cloneable=True
    _native_class_generator=True

    @property
    def _native_kind_tag(self):return 'immediate_generator_'+str(self.index)

    @property
    def _native_owned_kinds(self):return (self.record.outer,)


@dataclass
class GeneratorRecord:
    index:int
    plan:object
    node:object
    element:object
    semantic:object=None
    outer:object=None
    consumed:bool=False

    @property
    def kind(self):return GeneratorType(self.index,self)


class Generators:
    def __init__(self,model):
        self.model=model
        self.parents={id(child):node for node in model.iter_nodes()for child in ast.iter_child_nodes(node)}
        self.records=[]
        self.sites={}

    def _immediate(self,plan,node,environment):
        from .native_classes import shape
        parent=self.parents.get(id(node))
        if isinstance(parent,ast.Starred):
            call=self.parents.get(id(parent))
            return isinstance(call,ast.Call)and parent in call.args
        keyword=None
        if isinstance(parent,ast.keyword):
            keyword=parent.arg;parent=self.parents.get(id(parent))
            if keyword is None or not isinstance(parent,ast.Call):return False
            position=None
        else:
            if not isinstance(parent,ast.Call)or node not in parent.args:return False
            position=parent.args.index(node)
        from .native_module_calls import BuiltinRef
        def admitted(identity):
            if isinstance(identity,BuiltinIdentity):return keyword is None and position==0 and identity.name in CONSUMERS
            if isinstance(identity,BuiltinRef):
                adapter=self.model.callable_cells.member_adapters.get(identity.module)
                if keyword is not None:return keyword in getattr(adapter,'EAGER_KEYWORDS',{}).get(identity.name,())
                capabilities=getattr(adapter,'EAGER_ARGUMENTS',{})
                if identity.name in capabilities:
                    positions=capabilities[identity.name]
                    return positions is None or position in positions
            return False
        identity=self.model.builtin_identity(plan,parent.func,environment)if isinstance(parent.func,(ast.Name,ast.Attribute))else None
        linked=getattr(self.model.callable_cells,'linked_builtins',None)
        if linked is not None:identity=linked.identity(plan,parent.func,identity)
        if admitted(identity):return True
        value=self.model.records.get((plan.index,id(parent.func)))
        if value is not None:
            targets=[]
            for branch in alternatives(shape(value)):
                if not getattr(branch,'_native_function_reference',False):break
                targets.extend(branch.targets)
            else:
                if targets and all(admitted(target)for target in targets):return True
        if isinstance(parent.func,ast.Attribute):
            receiver=self.model.records.get((plan.index,id(parent.func.value)))
            if receiver is not None and shape(receiver)is None and not self.model.final:
                from .native_guard_flow import AnalysisPending
                raise AnalysisPending()
            if receiver is not None and shape(receiver)is not None:
                def accepted(kind):
                    adapters=(*self.model.callable_cells.member_adapters.values(),*self.model.callable_cells.method_adapters)
                    for adapter in adapters:
                        if keyword is not None:
                            capability=getattr(adapter,'eager_method_keyword',None)
                            if capability is not None and capability(kind,parent.func.attr,keyword):return True
                            continue
                        capability=getattr(adapter,'eager_method_arguments',None)
                        positions=None if capability is None else capability(kind,parent.func.attr)
                        if positions is not None and position in positions:return True
                    return False
                return all(accepted(kind)for kind in alternatives(shape(receiver)))
        return False

    def analyze(self,plan,node,environment):
        from .native_classes import Cell,ClassUnsupported
        from .native_class_comprehensions import _normalizer
        if not self._immediate(plan,node,environment):
            raise ClassUnsupported(node,'this generator expression needs general iteration or stored suspension state; only immediate builtin collectors are implemented, and a suspended comprehension frame retaining lexical bindings and nested-loop positions is still required',proof='nonescaping generator consumer and retained suspension state')
        key=plan.index,id(node)
        record=self.sites.get(key)
        if record is None:
            record=GeneratorRecord(len(self.records),plan,node,Cell())
            self.sites[key]=record;self.records.append(record)
        record.semantic=_normalizer(self.model,plan,environment).comprehension(node)
        first=self.model.expression(plan,node.generators[0].iter,environment)
        record.outer=self.model.iterators.source(plan,node,first,('generator_outer',record.index))
        return self.model.cell(plan,node,record.kind)

    def demand(self,plan,node,value,environment):
        from .native_classes import Cell
        from .native_class_comprehensions import analyze
        record=value.root().tag.record
        from .native_generator_effects import ensure_protocol
        ensure_protocol(self.model,record.node,analysis_only=True)
        def contribute(inside,semantic):
            self.model.contribute(record.element,self.model.expression(plan,semantic.element,inside),semantic.element)
            return record.element
        analyze(self.model,plan,record.node,environment,contribute=contribute,
                first_value=Cell(record.outer),semantic=record.semantic)
        return record.element

    def snapshot(self):
        from .native_classes import shape
        return tuple((record.index,shape(record.element),None if record.outer is None else record.outer.index)for record in self.records)

    def construct(self,emitter,node):
        from .native_classes import Expression
        record=self.sites[(emitter.plan.index,id(node))]
        setup,first=emitter.capture(emitter.expression(node.generators[0].iter))
        outer=self.model.iterators.construct(emitter,node,first,kind=record.outer)
        return Expression('{'+setup+outer.code+'}',record.kind)

    @contextmanager
    def context(self,emitter,scope,binding_scope):
        old=getattr(emitter,'logical_scope',None)
        old_binding=getattr(emitter,'logical_binding_scope',None)
        old_numeric_scope=emitter.numeric.scope_code
        emitter.logical_scope=scope;emitter.logical_binding_scope=binding_scope
        emitter.numeric.scope_code=emitter.location_code
        try:yield
        finally:
            if old is None:emitter.__dict__.pop('logical_scope',None)
            else:emitter.logical_scope=old
            if old_binding is None:emitter.__dict__.pop('logical_binding_scope',None)
            else:emitter.logical_binding_scope=old_binding
            emitter.numeric.scope_code=old_numeric_scope

    def consume(self,emitter,node,name,value,arguments,keywords,wanted,*,append_item=None):
        from .native_classes import Expression,shape
        from .native_class_comprehensions import Collector,_Iterator,emit
        from .native_class_calls import synchronous
        from .native_generator_effects import ensure_protocol
        ensure_protocol(self.model,value.kind.record.node)
        record=value.kind.record;record.consumed=True
        caller_scope=getattr(emitter,'logical_scope',emitter.plan.scope)
        caller_binding=getattr(emitter,'logical_binding_scope',self.model.lexical.scope(emitter.plan))
        caller_location=emitter.location_code()
        generator_binding=self.model.unit.scope_for(record.node).ordinal
        stage=emitter.fresh();label='generator_result_'+emitter.fresh()
        def initialize(e,result,kind):
            if append_item is not None:return ''
            if name=='list':return f'let mut {result}:Vec<{e.rust_type(kind.element)}>=Vec::new();'
            if name=='sum':
                initial=arguments[1]if len(arguments)==2 else Expression(e.literal(0),'int',0)
                return f'let mut {result}={e.coerce(initial,kind,node)};'
            if name in {'min','max'}:return f'let mut {result}:Option<{e.rust_type(kind)}>=None;'
            return "'"+label+':{'
        def append(e,result,semantic):
            before,item=e.capture(e.expression(semantic.element))
            from .native_types import EmptyType
            if isinstance(item.kind,EmptyType):return before+'match '+item.code+'{};'
            action=''
            with self.context(e,caller_scope,caller_binding):
                if append_item is not None:action=append_item(e,item)
                elif name=='list':
                    reserve=e.at(f'{result}.try_reserve(1).map_err(|_|"MemoryError: cannot allocate list".to_owned())',node)
                    action=reserve+';'+f'{result}.push({e.coerce(item,wanted.element,node)});'
                elif name=='sum':
                    computed=e.numeric.binary(ast.Add(),e.scalar(Expression(result+'.clone()',wanted)),e.scalar(item),node)
                    action=f'{result}={e.coerce(computed,wanted,node)};'
                elif name in {'any','all'}:
                    truth=e.truth(item,node)
                    if name=='all':truth='!('+truth+')'
                    action=f'if {truth}{{break \'{label} {str(name=="any").lower()};}}'
                elif name=='next':action=f'break \'{label} {e.coerce(item,wanted,node)};'
                else:
                    candidate,old=e.fresh(),e.fresh()
                    comparison=e.comparison(ast.Lt()if name=='min'else ast.Gt(),Expression(candidate+'.clone()',wanted),Expression(old+'.clone()',wanted),node)
                    action=f'let {candidate}={e.coerce(item,wanted,node)};let replace=match &{result}{{Some({old})=>{comparison},None=>true}};if replace{{{result}=Some({candidate});}}'
            return before+f'{stage}=false;'+action+f'{stage}=true;'
        def finish(e,result,kind):
            with self.context(e,caller_scope,caller_binding):
                if append_item is not None:ending='()'
                elif name=='list':ending=f'class_list({result})'
                elif name=='sum':ending=result
                elif name in {'min','max'}:ending=e.at(f'{result}.ok_or_else(||"ValueError: {name}() iterable argument is empty".to_owned())',node)
                elif name=='next':
                    from .native_exception_values import stop_iteration
                    ending=(e.coerce(arguments[1],kind,node)if len(arguments)==2 else stop_iteration(e,node,kind))+'}'
                else:ending=str(name=='all').lower()+'}'
            return f'{stage}=false;'+ending
        with self.context(emitter,'<genexpr>',generator_binding):
            pulled=self.model.iterators.pull(emitter,record.node.generators[0].iter,Expression(value.code,record.outer))
            first=_Iterator('',pulled.kind,pulled.code)
            body=emit(emitter,record.node,collector=Collector(initialize,append,finish),first=first,wanted=wanted).code
        result=emitter.fresh();guard=emitter.fresh()
        invoke=('(||{Ok::<'+emitter.rust_type(wanted)+',NativeError>('+body+')})()'if synchronous(self.model,emitter.plan)
                else '(async{Ok::<'+emitter.rust_type(wanted)+',NativeError>('+body+')}).await')
        stop=(f'error=class_exception_generator_stop(error,{node.lineno},{caller_location});'if self.model.exceptions.used else
              f'error=NativeError{{message:"RuntimeError: generator raised StopIteration".to_owned(),line:{node.lineno},function:{caller_location},frames:Vec::new()}};')
        catch=(f'{invoke}.map_err(|mut error|{{if {stage}{{'
               f'if error.message=="StopIteration"||error.message.starts_with("StopIteration:"){{error=NativeError{{message:"RuntimeError: generator raised StopIteration".to_owned(),line:{node.lineno},function:{caller_location},frames:Vec::new()}};}}'
               f'else{{error.frames.push(({node.lineno},{caller_location}));}}}}error}})?')
        if self.model.exceptions.used:
            original=f'error=NativeError{{message:"RuntimeError: generator raised StopIteration".to_owned(),line:{node.lineno},function:{caller_location},frames:Vec::new()}};'
            catch=catch.replace(original,stop)
            from .native_exception_values import is_stop
            catch=catch.replace('error.message=="StopIteration"||error.message.starts_with("StopIteration:")',is_stop(emitter,'error'))
        return Expression('{'+f'let {guard}=class_generator_enter(&class_scope,{node.lineno},{caller_location})?;let mut {stage}=true;let {result}={catch};{result}'+'}',wanted)

    def runtime(self,source):
        if not any(record.consumed for record in self.records):return source
        assert source.count('limit: usize }')==1
        source=source.replace('limit: usize }','limit: usize, generator_depth: usize }',1)
        assert source.count('limit:1000}')==1
        source=source.replace('limit:1000}','limit:1000,generator_depth:0}',1)
        source=source.replace('control.depth>=control.limit','control.depth.saturating_add(control.generator_depth)>=control.limit')
        return source+'''\nstruct ClassGeneratorDepth(Rc<RefCell<ClassControl>>);
impl Drop for ClassGeneratorDepth{fn drop(&mut self){self.0.borrow_mut().generator_depth-=1;}}
fn class_generator_enter(scope:&ClassScope,line:usize,caller:&'static str)->ClassResult<ClassGeneratorDepth>{
 {let mut control=scope.control.borrow_mut();
 if control.depth.saturating_add(control.generator_depth)>=control.limit{return Err(NativeError{message:"RecursionError: maximum recursion depth exceeded".into(),line,function:caller,frames:Vec::new()});}
 control.generator_depth+=1;}
 Ok(ClassGeneratorDepth(scope.control.clone()))
}\n'''
