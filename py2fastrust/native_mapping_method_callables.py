"""Captured canonical dictionary methods with their original receiver identity."""
import ast
from dataclasses import dataclass
from .native_types import alternatives,EMPTY

METHODS=frozenset({'__getitem__','get','setdefault','popitem','update','pop'})


@dataclass(frozen=True)
class MappingMethod:
    receiver:object
    name:str
    _native_bound_mapping_method=True
    _native_stored_reference=True
    _native_reference_cloneable=True
    _native_python_type_name='builtin_function_or_method'
    @property
    def _native_kind_tag(self):return 'mapping_method_'+str(self.receiver.index)+'_'+self.name
    @property
    def _native_owned_kinds(self):return(self.receiver,)
    @property
    def rust(self):return 'Rc<NativeMappingMethod_'+str(self.receiver.index)+'_'+self.name+'>'


@dataclass
class Invocation:
    result:object
    error:str|None=None


def is_method(kind):return isinstance(kind,MappingMethod)


def callable_kind(kind):
    from .native_aot_callables import function_kind
    return function_kind(kind)or is_method(kind)or getattr(kind,'_native_builtin_type',False)


def supported(kind,name):
    from .native_class_mappings import mapping_kind
    return(name in METHODS and mapping_kind(kind)and kind.record.category=='dict'
           and(name!='update'or kind.record.flavor in {'dict','defaultdict'}))


def requires_frames(unit,analysis):
    from .native_constraints import Allocation
    from .native_key_types import DictType
    parents={id(child):node for node in ast.walk(unit.tree)for child in ast.iter_child_nodes(node)}
    for node in ast.walk(unit.tree):
        if not isinstance(node,ast.Attribute)or node.attr not in METHODS:continue
        parent=parents.get(id(node))
        if (node.attr=='popitem'and isinstance(parent,ast.Call)and parent.func is node
                and not parent.args and not parent.keywords):continue
        ordinal=unit.ordinal(node.value)
        for facts in analysis.scopes.values():
            value=facts.values.get(ordinal)
            if value is not None and any(isinstance(part,Allocation)and part.category=='dict'or isinstance(part,DictType)for part in value.alternatives):return True
    return False


def acquire(model,plan,node,receiver):
    from .native_classes import shape
    if not isinstance(node,ast.Attribute):return None
    kinds=alternatives(shape(receiver))
    if not kinds or not all(supported(kind,node.attr)for kind in kinds):return None
    if node.attr=='popitem':
        from .native_mapping_popitem import require_origin
        require_origin(model,node,kinds)
    if node.attr=='pop':
        from .native_mapping_pop import require_origin
        require_origin(model,node,kinds)
    if node.attr=='update':
        from .native_mapping_update import require_origin
        require_origin(model,node,kinds)
    registry=getattr(model,'mapping_method_types',None)
    if registry is None:
        registry=model.mapping_method_types=set()
        from .native_callback_effects import register
        register(model,lambda plan,node:any(kind.name in {'setdefault','update','pop'}or kind.receiver.record.flavor=='defaultdict'for kind in getattr(model,'mapping_method_calls',{}).get((plan.index,id(node)),())))
    result=model.cell(plan,node)
    for kind in kinds:
        method=MappingMethod(kind,node.attr);registry.add(method)
        model.contribute(result,model.cell_for_kind(method),node)
    return model.remember(plan,node,result)


def read(emitter,node,wanted):
    from .native_classes import Expression
    from .native_unions import project
    if not isinstance(node,ast.Attribute):return None
    choices=alternatives(wanted)
    if not choices or not all(is_method(kind)for kind in choices):return None
    setup,receiver=emitter.capture(emitter.expression(node.value))
    def branch(kind,code):
        method=MappingMethod(kind,node.attr)
        value=Expression('Rc::new(NativeMappingMethod_'+str(kind.index)+'_'+node.attr+'{receiver:('+code+').clone()})',method)
        return emitter.coerce(value,wanted,node)
    return Expression('{'+setup+project(receiver.kind,receiver.code,branch)+'}',wanted)


def binding_error(kind,count,keywords):
    name=kind.name;record=kind.receiver.record
    if name=='popitem':
        from .native_mapping_popitem import binding_error as popitem_error
        return popitem_error(count,keywords)
    if name=='pop':
        from .native_mapping_pop import binding_error as pop_error
        return pop_error(count,keywords)
    if name=='update':
        from .native_mapping_update import binding_error as update_error
        return update_error(count)
    owner='Counter'if record.flavor=='Counter'else'defaultdict'if record.flavor=='defaultdict'else'dict'
    if keywords:return f'TypeError: {owner}.{name}() takes no keyword arguments'
    if name=='__getitem__':return None if count==1 else f'TypeError: {owner}.__getitem__() takes exactly one argument ({count} given)'
    if count<1:return f'TypeError: {name} expected at least 1 argument, got {count}'
    if count>2:return f'TypeError: {name} expected at most 2 arguments, got {count}'
    return None


def analyze_call(model,plan,node,kind,positional,keywords,environment,*,identity=None):
    from .native_classes import Cell
    if kind.name=='pop':
        from .native_mapping_pop import analyze_values
        return analyze_values(model,plan,node,Cell(kind.receiver),positional,keywords,identity=('captured_pop',identity,kind))
    if kind.name=='update':
        from .native_mapping_update import analyze_values
        return analyze_values(model,plan,node,Cell(kind.receiver),positional,keywords,environment,identity=('captured_update',identity,kind))
    error=binding_error(kind,len(positional),keywords)
    result=model.cell(plan,node,identity=('mapping_method_call',identity,kind))
    if error:
        model.contribute(result,Cell(EMPTY),node)
        return Invocation(result,error)
    calls=getattr(model,'mapping_method_calls',None)
    if calls is None:calls=model.mapping_method_calls={}
    calls.setdefault((plan.index,id(node)),set()).add(kind)
    record=kind.receiver.record
    if kind.name=='popitem':
        value=Cell('tuple',(record.key,record.value))
        if not model.namespace.contribute(result,value,node,force=True):model.contribute(result,value,node)
        return Invocation(result)
    if kind.name=='__getitem__':model.mappings.defaultdicts.analyze_get(plan,node,record,positional[0],environment)
    if kind.name=='setdefault':
        model.mappings.contribute_key(record,positional[0],node)
        model.contribute(record.value,positional[1]if len(positional)==2 else Cell('none'),node)
    model.contribute(result,record.value,node)
    if kind.name!='__getitem__':model.contribute(result,positional[1]if len(positional)==2 else Cell('none'),node)
    return Invocation(result)


def emit_call(emitter,node,kind,record,callee,positional,keywords,wanted):
    from .native_classes import Expression,shape
    from .native_class_builtins import _error
    from .native import _string
    if record.error:return _error(emitter,node,wanted,_string(record.error)+'.to_owned()')
    owner=Expression('('+callee+').receiver.clone()',kind.receiver)
    if kind.name=='pop':
        from .native_mapping_pop import emit_values
        return emit_values(emitter,node,record,owner,positional,keywords,wanted)
    if kind.name=='update':
        from .native_mapping_update import emit_values
        return emit_values(emitter,node,record,owner,positional,keywords,wanted)
    if kind.name=='popitem':
        from .native_mapping_popitem import remove
        return remove(emitter,node,owner,wanted)
    key=positional[0]
    if kind.name=='__getitem__':return emitter.model.mappings.emit_get(emitter,node,owner,key,wanted)
    default=positional[1]if len(positional)==2 else Expression('()','none')
    if kind.name=='get':return emitter.model.mappings.emit_get(emitter,node,owner,key,wanted,default)
    from .native_unions import project
    value,lookup,hashed=(emitter.fresh()for _ in range(3))
    from .native_class_mappings import query_canonical
    query=query_canonical(emitter,key,shape(kind.receiver.record.key))
    found='{let '+lookup+'=match '+query+'{Some('+hashed+')=>'+owner.code+'.borrow().get(&'+hashed+').cloned(),None=>None};'+lookup+'}'
    present=emitter.coerce(Expression(value,shape(kind.receiver.record.value)),wanted,node)
    absent=emitter.model.mappings.emit_store(emitter,node,owner,key,default)+emitter.coerce(default,wanted,node)
    return Expression('match '+found+'{Some('+value+')=>'+present+',None=>{'+absent+'}}',wanted)


def comparison(emitter,operator,left,right,node):
    if not(is_method(left.kind)or is_method(right.kind)):return None
    from .native_classes import ClassUnsupported
    if isinstance(operator,(ast.Eq,ast.NotEq,ast.Is,ast.IsNot)):
        same=is_method(left.kind)and left.kind==right.kind
        if not same:code='false'
        elif isinstance(operator,(ast.Is,ast.IsNot)):code='Rc::ptr_eq(&('+left.code+'),&('+right.code+'))'
        else:code='Rc::ptr_eq(&('+left.code+').receiver,&('+right.code+').receiver)'
        return '!('+code+')'if isinstance(operator,(ast.NotEq,ast.IsNot))else code
    raise ClassUnsupported(node,'ordering or containment involving a captured builtin mapping method needs its nonnumeric observer adapter',types=(('left',left.kind),('right',right.kind)),proof='captured mapping method observer')


def runtime(model,emitter):
    return '\n'.join('struct NativeMappingMethod_'+str(kind.receiver.index)+'_'+kind.name+'{receiver:'+emitter.rust_type(kind.receiver)+'}'for kind in sorted(getattr(model,'mapping_method_types',()),key=lambda kind:(kind.receiver.index,kind.name)))
