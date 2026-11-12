"""Direct typed numeric special-method dispatch over retained source functions."""
import ast
from dataclasses import dataclass,field

from .call_semantics import Argument,CallArguments
from .native_builtin_singletons import NOT_IMPLEMENTED


BINARY={
 ast.Add:('add','+'),ast.Sub:('sub','-'),ast.Mult:('mul','*'),ast.MatMult:('matmul','@'),
 ast.Div:('truediv','/'),ast.FloorDiv:('floordiv','//'),ast.Mod:('mod','%'),
 ast.Pow:('pow','** or pow()'),ast.LShift:('lshift','<<'),ast.RShift:('rshift','>>'),
 ast.BitAnd:('and','&'),ast.BitOr:('or','|'),ast.BitXor:('xor','^')}
UNARY={ast.UAdd:('__pos__','+'),ast.USub:('__neg__','-'),ast.Invert:('__invert__','~')}
UNARY_SLOTS=frozenset(name for name,_ in UNARY.values())
SUPPORTED_SLOTS=UNARY_SLOTS|{'__iter__','__str__','__repr__'}

BINARY_SLOTS=frozenset('__'+prefix+name+'__'for name,_ in BINARY.values()for prefix in ('','r','i'))
COMPARISON={ast.Eq:('__eq__','__eq__','=='),ast.NotEq:('__ne__','__ne__','!='),ast.Lt:('__lt__','__gt__','<'),ast.LtE:('__le__','__ge__','<='),ast.Gt:('__gt__','__lt__','>'),ast.GtE:('__ge__','__le__','>=')}
COMPARISON_SLOTS=frozenset(name for first,second,_ in COMPARISON.values()for name in (first,second))
SUPPORTED_SLOTS|=BINARY_SLOTS|COMPARISON_SLOTS


@dataclass
class Phase:
    member:object
    reverse:bool
    site:object
    negate:bool=False


@dataclass
class Branch:
    left:object
    right:object
    phases:list=field(default_factory=list)
    fallback:object=None
    complete:bool=False


@dataclass
class BinarySite:
    result:object
    operator:object
    branches:dict=field(default_factory=dict)


class Operators:
    def __init__(self,model):
        self.model=model
        self.sites={}
        self.unary_sites={}
        self.comparison_sites={}
        from .native_callback_effects import register
        register(model,self.may_call)

    def may_call(self,plan,node):
        prefix=(plan.index,id(node))
        return (any(key[:2]==prefix and any(branch.phases for branch in site.branches.values())for key,site in self.sites.items())
                or any(key[:2]==prefix and any(branch.phases for branch in site.branches.values())for key,site in self.unary_sites.items())
                or any(key[:2]==prefix and any(branch.phases for branch in site.branches.values())for key,site in self.comparison_sites.items()))

    def _slot(self,kind,name,node):
        from .native_classes import InstanceType,ClassUnsupported
        if not isinstance(kind,InstanceType):return None
        owner=self.model.classes[kind.name]
        method=owner.methods.get(name)
        if method is None:return None
        registry=getattr(self.model,'class_namespaces',None)
        if registry is None:
            raise ClassUnsupported(node,"source numeric special methods require the retained source class namespace and function reference",proof="numeric source method identity")
        member=registry.member(owner,name)
        if member.descriptor!='function':
            raise ClassUnsupported(node,"this numeric special method uses a nonfunction descriptor; descriptor-aware implicit arithmetic calls are not implemented",proof="numeric special-method descriptor binding")
        registry.observe_method(member,node)
        return member

    def _include(self,result,value,node):
        from .native_classes import shape
        from .native_union_sequences import branches
        for child in branches(value):
            kind=shape(child)
            if kind is None or kind==NOT_IMPLEMENTED:continue
            if not self.model.namespace.contribute(result,child,node,force=True):self.model.contribute(result,child,node)

    def binary(self,plan,node,operator,left,right,environment,*,identity=None):
        from .native_classes import Cell,shape,InstanceType,ClassUnsupported,merge
        from .native_types import alternatives
        from .native_union_sequences import branches
        from .native_aot_callables import analyze_values
        if not any(isinstance(kind,InstanceType)or kind==NOT_IMPLEMENTED for value in (left,right)for kind in alternatives(shape(value))):return None
        spec=BINARY.get(type(operator))
        if spec is None:raise ClassUnsupported(node,"this source numeric operation has no registered original-operator slot plan",proof="registered numeric operator slots")
        if environment is None:
            raise ClassUnsupported(node,"source numeric special methods may mutate bindings; this implicit arithmetic caller does not yet supply its original typed environment",proof="source operator callback effects and argument environment")
        key=(plan.index,id(node),identity)
        site=self.sites.setdefault(key,BinarySite(self.model.cell(plan,node,identity=identity),operator))
        site.branches={}
        name,_=spec
        for first in branches(left):
            for second in branches(right):
                a,b=shape(first),shape(second)
                branch=Branch(first,second);site.branches[(a,b)]=branch
                candidates=[]
                if isinstance(node,ast.AugAssign):candidates.append((a,'__i'+name+'__',False))
                candidates.append((a,'__'+name+'__',False))
                if a!=b:candidates.append((b,'__r'+name+'__',True))
                stopped=False
                for index,(kind,slot,reverse)in enumerate(candidates):
                    member=self._slot(kind,slot,node)
                    if member is None:continue
                    args=[second,first]if reverse else[first,second]
                    metadata=CallArguments((Argument(node),Argument(node)),())
                    callback=analyze_values(self.model.callable_cells,plan,node,member.function_cell,metadata,args,[],environment,identity=('numeric_phase',identity,a,b,index))
                    phase=Phase(member,reverse,callback);branch.phases.append(phase)
                    self._include(site.result,callback.result,node)
                    returned=shape(callback.result)
                    if returned is None:
                        stopped=True;break
                    if NOT_IMPLEMENTED not in alternatives(returned):
                        branch.complete=True;stopped=True;break
                if not stopped:
                    if isinstance(a,InstanceType)or isinstance(b,InstanceType)or a==NOT_IMPLEMENTED or b==NOT_IMPLEMENTED:
                        branch.fallback='error'
                    else:
                        branch.fallback=self.model.binary_builtin(plan,node,operator,first,second,identity=('numeric_builtin',identity,a,b))
                        self._include(site.result,branch.fallback,node)
                    branch.complete=True
        if self.model.final and shape(site.result)is None:
            # A never-returning augmented operation still shares its original
            # target slot. Its error expression can use that slot's existing
            # ABI without introducing an impossible None value into storage.
            never_returns=all(branch.complete and branch.fallback=='error'for branch in site.branches.values())
            if isinstance(node,ast.AugAssign)and never_returns:
                self.model.contribute(site.result,left,node)
            else:merge(site.result,Cell('none'),node)
        return site.result

    def emit_binary(self,emitter,operator,left,right,node,wanted,*,identity=None):
        from .native_classes import Expression,shape,ClassUnsupported
        from .native_unions import project,union_kind
        site=self.sites.get((emitter.plan.index,id(node),identity))
        if site is None:return None
        def emit_pair(first,second):
            branch=site.branches[(first.kind,second.kind)]
            if not branch.complete:
                raise ClassUnsupported(node,"numeric callback return alternatives remain unresolved before native emission",proof="complete numeric method result alternatives")
            def step(index):
                if index==len(branch.phases):
                    if branch.fallback=='error':return self._error(emitter,operator,first,second,node,wanted)
                    if branch.fallback is None:raise ClassUnsupported(node,"numeric dispatch has no proved terminal result or fallback",proof="complete numeric dispatch chain")
                    return emitter.binary_builtin(operator,first,second,node,wanted).code
                phase=branch.phases[index]
                manager=second if phase.reverse else first
                owner=phase.member.owner
                args=[Expression(value.code+'.clone()',value.kind)for value in ([second,first]if phase.reverse else[first,second])]
                from .native_class_value_demands import direct_operator
                direct=direct_operator(emitter,node,phase,args,shape(phase.site.result))
                if direct is not None:
                    before,outcome=emitter.capture(direct)
                    def select_direct(kind,code):
                        if kind==NOT_IMPLEMENTED:return step(index+1)
                        return emitter.coerce(Expression('('+code+').clone()',kind),wanted,node)
                    code=project(outcome.kind,outcome.code,select_direct)if union_kind(outcome.kind)else select_direct(outcome.kind,outcome.code)
                    return '{'+before+code+'}'
                from .native_module_linking import ClassReferenceType
                reference=emitter.fresh()
                setup=f'let {reference}={{{manager.code}.borrow().class_definition.clone()}};'
                function=emitter.model.class_namespaces.emit_get(emitter,node,Expression(reference,ClassReferenceType(owner.index)),phase.member)
                before,function=emitter.capture(function);setup+=before
                args=[Expression(value.code+'.clone()',value.kind)for value in ([second,first]if phase.reverse else[first,second])]
                from .native_aot_callables import emit_values
                from .native_class_binding_contexts import CapturedClassContext
                context=CapturedClassContext(phase.member,Expression(reference,ClassReferenceType(owner.index)))
                outcome=emit_values(emitter,node,phase.site,function,args,[],shape(phase.site.result),captured_class_context=context)
                before,outcome=emitter.capture(outcome);setup+=before
                def select(kind,code):
                    if kind==NOT_IMPLEMENTED:return step(index+1)
                    return emitter.coerce(Expression('('+code+').clone()',kind),wanted,node)
                code=project(outcome.kind,outcome.code,select)if union_kind(outcome.kind)else select(outcome.kind,outcome.code)
                return '{'+setup+code+'}'
            return step(0)
        def right_branch(first):
            return project(right.kind,right.code,lambda kind,code:emit_pair(first,Expression('('+code+').clone()',kind)))if union_kind(right.kind)else emit_pair(first,right)
        code=project(left.kind,left.code,lambda kind,code:right_branch(Expression('('+code+').clone()',kind)))if union_kind(left.kind)else right_branch(left)
        return Expression(code,wanted)

    def unary(self,plan,node,operator,value,environment):
        from .native_classes import shape,Cell,InstanceType,ClassUnsupported,merge
        from .native_types import alternatives
        from .native_union_sequences import branches
        from .native_aot_callables import analyze_values
        if not any(isinstance(kind,InstanceType)or kind==NOT_IMPLEMENTED for kind in alternatives(shape(value))):return None
        spec=UNARY.get(type(operator))
        if spec is None:raise ClassUnsupported(node,"this unary source operation has no registered numeric method slot",proof="unary numeric special-method plan")
        key=plan.index,id(node)
        site=self.unary_sites.setdefault(key,BinarySite(self.model.cell(plan,node),operator));site.branches={}
        for child in branches(value):
            kind=shape(child);branch=Branch(child,None);site.branches[kind]=branch
            member=self._slot(kind,spec[0],node)
            if member is not None:
                metadata=CallArguments((Argument(node),),())
                callback=analyze_values(self.model.callable_cells,plan,node,member.function_cell,metadata,[child],[],environment,identity=('unary_numeric',kind))
                branch.phases=[Phase(member,False,callback)]
                self.model.contribute(site.result,callback.result,node)
                branch.complete=shape(callback.result)is not None
            elif isinstance(kind,InstanceType)or kind==NOT_IMPLEMENTED:branch.fallback='error';branch.complete=True
            elif kind in {'int','bool','int_bool','float'}:
                if kind=='float'and isinstance(operator,ast.Invert):branch.fallback='error'
                else:
                    branch.fallback=Cell('float'if kind=='float'else'int');self.model.contribute(site.result,branch.fallback,node)
                branch.complete=True
            else:branch.fallback='error';branch.complete=True
        if self.model.final and shape(site.result)is None:merge(site.result,Cell('none'),node)
        return site.result

    def emit_unary(self,emitter,node,operator,value,wanted):
        from .native_classes import Expression,shape,ClassUnsupported
        from .native_unions import project,union_kind
        from .native_aot_callables import emit_values
        from .native_module_linking import ClassReferenceType
        from .native_class_builtins import _type_name,_error
        from .native import _string
        site=self.unary_sites.get((emitter.plan.index,id(node)))
        if site is None:return None
        def branch(kind,code):
            planned=site.branches[kind];current=Expression('('+code+').clone()',kind)
            if not planned.complete:raise ClassUnsupported(node,"unary source method result remains unresolved",proof="complete unary numeric result")
            if planned.phases:
                phase=planned.phases[0];owner=phase.member.owner;reference=emitter.fresh()
                setup=f'let {reference}={{{current.code}.borrow().class_definition.clone()}};'
                fn=self.model.class_namespaces.emit_get(emitter,node,Expression(reference,ClassReferenceType(owner.index)),phase.member)
                before,fn=emitter.capture(fn);setup+=before
                from .native_class_binding_contexts import CapturedClassContext
                context=CapturedClassContext(phase.member,Expression(reference,ClassReferenceType(owner.index)))
                result=emit_values(emitter,node,phase.site,fn,[current],[],wanted,captured_class_context=context)
                return '{'+setup+result.code+'}'
            if planned.fallback=='error':
                template='TypeError: bad operand type for unary '+UNARY[type(operator)][1]+": '{}'"
                return _error(emitter,node,wanted,'format!('+_string(template)+','+_type_name(emitter,current,node)+')').code
            return emitter.unary_builtin(operator,current,node,wanted).code
        code=project(value.kind,value.code,branch)if union_kind(value.kind)else branch(value.kind,value.code)
        return Expression(code,wanted)

    def _has_comparison(self,kind):
        from .native_classes import InstanceType
        from .native_types import alternatives
        return any(isinstance(child,InstanceType)and COMPARISON_SLOTS.intersection(self.model.classes[child.name].methods)for child in alternatives(kind))

    def _nested_comparison(self,kind):
        from .native_types import ListType,TupleType,TupleSequenceType,alternatives
        for child in alternatives(kind):
            if isinstance(child,(ListType,TupleSequenceType)):
                if self._has_comparison(child.element)or self._nested_comparison(child.element):return True
            if isinstance(child,TupleType):
                if any(self._has_comparison(field)or self._nested_comparison(field)for field in child.fields):return True
        return False

    def comparison(self,plan,node,index,operator,left,right,environment):
        from .native_classes import Cell,shape,ClassUnsupported,InstanceType,merge
        from .native_union_sequences import branches
        from .native_types import alternatives
        from .native_aot_callables import analyze_values
        if isinstance(operator,(ast.Is,ast.IsNot)):return None
        a,b=shape(left),shape(right)
        if self._nested_comparison(a)or self._nested_comparison(b):
            raise ClassUnsupported(node,"this container comparison can invoke user special-method callbacks (__eq__, __ne__, __lt__, __le__, __gt__, __ge__); fallible live-element iteration and identity shortcuts are not implemented by the current container comparator",proof="implicit container rich-comparison callback demand")
        if type(operator)not in COMPARISON:return None
        if not(self._has_comparison(a)or self._has_comparison(b)):return None
        key=plan.index,id(node),index
        site=self.comparison_sites.setdefault(key,BinarySite(self.model.cell(plan,node,identity=('rich_comparison',index)),operator));site.branches={}
        slots=COMPARISON[type(operator)]
        for first in branches(left):
            for second in branches(right):
                a,b=shape(first),shape(second);branch=Branch(first,second);site.branches[(a,b)]=branch
                stopped=False
                for rank,(kind,slot,reverse)in enumerate(((a,slots[0],False),(b,slots[1],True))):
                    member=self._slot(kind,slot,node);negate=False
                    if member is None and isinstance(operator,ast.NotEq):member=self._slot(kind,'__eq__',node);negate=member is not None
                    if member is None:continue
                    args=[second,first]if reverse else[first,second]
                    metadata=CallArguments((Argument(node),Argument(node)),())
                    callback=analyze_values(self.model.callable_cells,plan,node,member.function_cell,metadata,args,[],environment,identity=('rich_phase',index,a,b,rank))
                    branch.phases.append(Phase(member,reverse,callback,negate))
                    returned=shape(callback.result)
                    if returned is None:stopped=True;break
                    if negate:
                        if any(kind!=NOT_IMPLEMENTED for kind in alternatives(returned)):self.model.contribute(site.result,Cell('bool'),node)
                    else:self._include(site.result,callback.result,node)
                    if NOT_IMPLEMENTED not in alternatives(returned):branch.complete=True;stopped=True;break
                if not stopped:
                    branch.fallback='builtin';branch.complete=True
                    self.model.contribute(site.result,Cell('bool'),node)
        if self.model.final and shape(site.result)is None:merge(site.result,Cell('none'),node)
        return site.result

    def emit_comparison(self,emitter,node,index,operator,left,right):
        from .native_classes import Expression,shape,InstanceType,ClassUnsupported
        from .native_unions import project,union_kind
        from .native_aot_callables import emit_values
        from .native_module_linking import ClassReferenceType
        site=self.comparison_sites.get((emitter.plan.index,id(node),index))
        if site is None:return None
        wanted=shape(site.result)
        def pair(first,second):
            branch=site.branches[(first.kind,second.kind)]
            if not branch.complete:raise ClassUnsupported(node,"rich-comparison callback result remains unresolved",proof="complete rich-comparison return alternatives")
            def step(rank):
                if rank==len(branch.phases):
                    if isinstance(operator,(ast.Eq,ast.NotEq))and(any(isinstance(value.kind,InstanceType)or value.kind==NOT_IMPLEMENTED for value in (first,second))):
                        identity=emitter.comparison_builtin(ast.Is()if isinstance(operator,ast.Eq)else ast.IsNot(),first,second,node)
                        return emitter.coerce(Expression(identity,'bool'),wanted,node)
                    value=emitter.comparison_builtin(operator,first,second,node)
                    return emitter.coerce(Expression(value,'bool'),wanted,node)
                phase=branch.phases[rank];manager=second if phase.reverse else first;reference=emitter.fresh()
                setup=f'let {reference}={{{manager.code}.borrow().class_definition.clone()}};'
                fn=self.model.class_namespaces.emit_get(emitter,node,Expression(reference,ClassReferenceType(phase.member.owner.index)),phase.member)
                before,fn=emitter.capture(fn);setup+=before
                args=[Expression(value.code+'.clone()',value.kind)for value in ([second,first]if phase.reverse else[first,second])]
                from .native_class_binding_contexts import CapturedClassContext
                context=CapturedClassContext(phase.member,Expression(reference,ClassReferenceType(phase.member.owner.index)))
                outcome=emit_values(emitter,node,phase.site,fn,args,[],shape(phase.site.result),captured_class_context=context);before,outcome=emitter.capture(outcome);setup+=before
                def select(kind,code):
                    if kind==NOT_IMPLEMENTED:return step(rank+1)
                    value=Expression('('+code+').clone()',kind)
                    if phase.negate:value=Expression('!('+emitter.truth(value,node)+')','bool')
                    return emitter.coerce(value,wanted,node)
                value=project(outcome.kind,outcome.code,select)if union_kind(outcome.kind)else select(outcome.kind,outcome.code)
                return '{'+setup+value+'}'
            return step(0)
        def right_for(first):return project(right.kind,right.code,lambda kind,code:pair(first,Expression('('+code+').clone()',kind)))if union_kind(right.kind)else pair(first,right)
        code=project(left.kind,left.code,lambda kind,code:right_for(Expression('('+code+').clone()',kind)))if union_kind(left.kind)else right_for(left)
        return Expression(code,wanted)

    def emit_compare_expression(self,emitter,node,wanted):
        from .native_classes import Expression
        if not any(key[:2]==(emitter.plan.index,id(node))for key in self.comparison_sites):return None
        before,left=emitter.capture(emitter.expression(node.left))
        def tail(index,left):
            setup,right=emitter.capture(emitter.expression(node.comparators[index]))
            value=self.emit_comparison(emitter,node,index,node.ops[index],left,right)
            if value is None:value=Expression(emitter.comparison_builtin(node.ops[index],left,right,node),'bool')
            more,value=emitter.capture(value);setup+=more
            retained=emitter.coerce(value,wanted,node)
            if index+1==len(node.ops):return '{'+setup+retained+'}'
            return '{'+setup+'if '+emitter.truth(value,node)+'{'+tail(index+1,right)+'}else{'+retained+'}}'
        return Expression('{'+before+tail(0,left)+'}',wanted)

    def implicit_comparison_guard(self,emitter,operator,left,right,node):
        from .native_classes import ClassUnsupported
        if type(operator)in COMPARISON and(self._has_comparison(left.kind)or self._has_comparison(right.kind)):
            raise ClassUnsupported(node,"this implicit comparator can call a user rich-comparison method, but its typed callback demand is not registered; direct comparison expressions are supported",proof="implicit rich-comparison callback demand and safe borrowing")

    def _error(self,emitter,operator,left,right,node,wanted):
        from .native import _string
        from .native_classes import domain
        from .native_class_builtins import _type_name,_error
        a,b=domain(left.kind),domain(right.kind)
        seq={'str','bytes','tuple','tuple_sequence','list'}
        if isinstance(operator,ast.Add)and a in seq:
            if isinstance(node,ast.AugAssign)and a=='list':template="'{}' object is not iterable"
            elif a=='bytes':template="can't concat {} to bytes"
            else:
                name='tuple'if a=='tuple_sequence'else a
                template='can only concatenate '+name+' (not "{}") to '+name
            values=[_type_name(emitter,right,node)]
        elif isinstance(operator,ast.Mult)and(a in seq or b in seq):
            other=right if a in seq else left
            template="can't multiply sequence by non-int of type '{}'";values=[_type_name(emitter,other,node)]
        else:
            template="unsupported operand type(s) for "+BINARY[type(operator)][1]+": '{}' and '{}'"
            values=[_type_name(emitter,left,node),_type_name(emitter,right,node)]
        return _error(emitter,node,wanted,'format!('+_string('TypeError: '+template)+','+','.join(values)+')').code
