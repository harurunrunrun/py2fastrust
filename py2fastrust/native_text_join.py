"""Builtin text joins over captured concrete sources and direct collectors."""
import ast
from dataclasses import dataclass


@dataclass
class JoinSite:
    element:object=None
    source_kind:object=None
    error:str|None=None


class TextJoinAdapter:
    @staticmethod
    def eager_method_arguments(kind,name):
        return frozenset({0})if kind in {'str','bytes'}and name=='join'else None

    @staticmethod
    def eager_method_keyword(kind,name,keyword):
        # Rejected keyword calls still construct their arguments, then raise
        # without demanding the generator's body or exposing its identity.
        return kind in {'str','bytes'}and name=='join'


def requires_frames(unit,analysis):
    from .native_constraints import MethodValue,IteratorValue
    from .native_types import ListType,TupleType,EmptyType
    from .native_text_receiver_facts import builtin_text_receiver_kinds
    nodes={unit.ordinal(node):node for node in ast.walk(unit.tree)}
    for facts in analysis.scopes.values():
        for ordinal,call in facts.calls.items():
            node=nodes.get(ordinal)
            for identity in call.identity.alternatives:
                if not isinstance(identity,MethodValue)or identity.name!='join':continue
                kinds=builtin_text_receiver_kinds(unit,facts,node,identity)
                if not kinds:continue
                if kinds!={'str'}or len(call.positional)!=1 or call.keywords:return True
                source=node.args[0]if isinstance(node,ast.Call)and len(node.args)==1 else None
                kind=facts.expressions.get(unit.ordinal(source))if source is not None else None
                # Preserve the existing ordinary backend's typed string-source
                # collector. Unknown or differently typed sources require the
                # registered cursor/error protocol before code generation.
                if kind=='str':continue
                if isinstance(kind,ListType)and(kind.element=='str'or isinstance(kind.element,EmptyType)):continue
                if isinstance(kind,TupleType)and kind.fields and all(field=='str'for field in kind.fields):continue
                if isinstance(source,ast.GeneratorExp):
                    parts=call.positional[0].alternatives
                    if parts and all(isinstance(part,IteratorValue)and not(part.item.unknown or part.item.unbound)and part.item.alternatives=={'str'}for part in parts):continue
                return True
    return False


def _sites(model):
    if not hasattr(model,'text_join_sites'):model.text_join_sites={}
    return model.text_join_sites


def analyze(model,plan,node,receiver,arguments,keywords,environment):
    from .native_classes import Cell,shape
    from .native_types import alternatives,ListType
    if node.func.attr!='join':return None
    kinds=alternatives(shape(receiver))
    if not kinds or not all(kind in {'str','bytes'}for kind in kinds):return None
    error='keywords'if keywords else'count'if len(arguments)!=1 else None
    if error is None and kinds==('str',)and shape(arguments[0])==ListType('str'):
        # A previous fixed-point iteration may have seen an unresolved source.
        # The exact builtin list now uses the existing direct join adapter.
        _sites(model).pop((plan.index,id(node)),None)
        return None
    site=JoinSite(error=error)
    _sites(model)[(plan.index,id(node))]=site
    if error is None:
        from .native_immediate_generators import GeneratorType
        if isinstance(shape(arguments[0]),GeneratorType):
            site.source_kind=shape(arguments[0])
            site.element=model.generators.demand(plan,node,arguments[0],environment)
        else:
            site.source_kind=model.iterators.source(plan,node,arguments[0],environment=environment)
            site.element=model.iterators.demand(plan,node,Cell(site.source_kind),environment)
    result=model.cell(plan,node)
    for kind in kinds:model.contribute(result,Cell(kind),node)
    return result


def emit(emitter,node):
    from .native_classes import Expression,shape
    from .native import _string
    from .native_types import EmptyType
    from .native_unions import project,union_kind
    from .native_immediate_generators import GeneratorType
    from .native_class_builtins import _type_name
    site=_sites(emitter.model).get((emitter.plan.index,id(node)))
    if site is None:return None
    setup,receiver=emitter.capture(emitter.expression(node.func.value))
    arguments=[]
    for value in node.args:
        before,value=emitter.capture(emitter.expression(value));setup+=before;arguments.append(value)
    for keyword in node.keywords:
        before,value=emitter.capture(emitter.expression(keyword.value));setup+=before
    wanted=emitter.kind(node)
    def error(kind,message):
        return emitter.at('Err::<'+emitter.rust_type(kind)+',String>('+message+')',node)
    if site.error:
        def invalid(kind,code):
            message=('TypeError: '+kind+'.join() takes no keyword arguments'if site.error=='keywords'else
                     'TypeError: '+kind+'.join() takes exactly one argument ('+str(len(arguments))+' given)')
            return error(wanted,_string(message)+'.to_owned()')
        code=project(receiver.kind,receiver.code,invalid)
        return Expression('{'+setup+code+'}',wanted)
    direct=integer_map_join(emitter,node,receiver,arguments[0])
    if direct is not None:return Expression('{'+setup+direct+'}',wanted)
    element=shape(site.element);values=emitter.fresh();item=emitter.fresh()
    setup+='let mut '+values+':Vec<'+emitter.rust_type(element)+'>=Vec::new();'
    def append(e,value):
        if isinstance(value.kind,EmptyType):return 'match '+value.code+'{};'
        reserved=e.at(values+'.try_reserve(1).map_err(|_|"MemoryError: join sequence is too large".to_owned())',node)
        return reserved+';'+values+'.push('+e.coerce(value,element,node)+');'
    if isinstance(site.source_kind,GeneratorType):
        consumed=emitter.model.generators.consume(emitter,node,'list',arguments[0],[],{},'none',append_item=append)
        setup+=consumed.code+';'
    else:
        source=emitter.model.iterators.construct(emitter,node,arguments[0],kind=site.source_kind,
            not_iterable=lambda kind:_string('TypeError: can only join an iterable')+'.to_owned()')
        before,source=emitter.capture(source);setup+=before
        pulled=emitter.model.iterators.pull(emitter,node,source)
        setup+='while let Some('+item+')=('+pulled.code+'){'+append(emitter,Expression(item,pulled.kind))+'}'
    def joined(kind,separator):
        result,index,current=(emitter.fresh()for _ in range(3))
        initial='String::new()'if kind=='str'else'Vec::<u8>::new()'
        def add(part,code):
            if isinstance(part,EmptyType):return 'match '+code+'{}'
            if part!=kind:
                name=_type_name(emitter,Expression(code,part),node)
                template=('TypeError: sequence item {}: expected str instance, {} found'if kind=='str'else
                          'TypeError: sequence item {}: expected a bytes-like object, {} found')
                return error('none','format!('+_string(template)+','+index+','+name+')')+';'
            length,extra=(emitter.fresh()for _ in range(2))
            overflow=_string('OverflowError: join() result is too long for a Python '+('string'if kind=='str'else'bytes'))
            capacity=(f'let {length}=({code}).len();let {extra}={length}.checked_add(if {index}==0{{0}}else{{({separator}).len()}})'
                      '.filter(|value|*value<=isize::MAX as usize).ok_or_else(||'+overflow+'.to_owned());')
            capacity+='let '+extra+'='+emitter.at(extra,node)+';'
            capacity+=emitter.at(result+'.try_reserve('+extra+').map_err(|_|"MemoryError: joined value is too large".to_owned())',node)+';'
            action='push_str'if kind=='str'else'extend_from_slice'
            return capacity+f'if {index}!=0{{{result}.{action}(&({separator}));}}{result}.{action}(&({code}));'
        action=project(element,current,lambda part,code:'{'+add(part,code)+'}')
        value='NativeText::from('+result+')'if kind=='str'else result
        code='{let mut '+result+'='+initial+';for ('+index+','+current+')in '+values+'.into_iter().enumerate(){'+action+'}'+value+'}'
        return emitter.coerce(Expression(code,kind),wanted,node)
    return Expression('{'+setup+project(receiver.kind,receiver.code,joined)+'}',wanted)


def integer_map_join(emitter,node,receiver,mapped):
    """Consume the real builtin cursor, formatting integers without text objects."""
    from .native_class_iterators import iterator_kind
    from .native_classes import shape,Expression
    from .references import BuiltinIdentity
    from .native_source_native_effects import readonly_pull
    kind=mapped.kind;model=emitter.model
    if receiver.kind!='str'or not iterator_kind(kind)or not model.iterators.owns(kind):return None
    record=kind.record
    if (record.operation!='map'or hasattr(record,'adapter')or len(record.input_types)!=1
            or getattr(shape(record.callback),'targets',())!=(BuiltinIdentity('str'),)):
        return None
    source_kind=record.input_types[0]
    if (not iterator_kind(source_kind)or not model.iterators.owns(source_kind)
            or shape(source_kind.record.element)!='int'or not readonly_pull(model,source_kind)):
        return None
    model.integer_join_writer=True
    source,item,writer,first=(emitter.fresh()for _ in range(4))
    pulled=model.iterators.pull(emitter,node,Expression(source,source_kind))
    failure='map_err(|_|'+writer+'.error.take().unwrap_or_else(||"RuntimeError: integer formatting failed".to_owned()))'
    separator=emitter.at(writer+'.write_str(&('+receiver.code+')).'+failure,node)+';'
    number=emitter.at('write!(&mut '+writer+',"{}",'+item+').'+failure,node)+';'
    return ('{let '+source+'='+mapped.code+'.borrow().source_0.clone();'
            'let mut '+writer+'=NativeIntegerJoin{output:String::new(),error:None};'
            'let mut '+first+'=true;while let Some('+item+')=('+pulled.code+'){'
            'if !'+first+'{'+separator+'}'+first+'=false;'+number+'}'
            'NativeText::from('+writer+'.output)}')


def runtime(model):
    if not getattr(model,'integer_join_writer',False):return ''
    return '''
struct NativeIntegerJoin{output:String,error:Option<String>}
impl std::fmt::Write for NativeIntegerJoin{
    fn write_str(&mut self,value:&str)->std::fmt::Result{
        if self.output.len().checked_add(value.len()).filter(|length|*length<=isize::MAX as usize).is_none(){
            self.error=Some("OverflowError: join() result is too long for a Python string".to_owned());
            return Err(std::fmt::Error);
        }
        if self.output.try_reserve(value.len()).is_err(){
            self.error=Some("MemoryError: joined value is too large".to_owned());
            return Err(std::fmt::Error);
        }
        self.output.push_str(value);Ok(())
    }
}
'''
