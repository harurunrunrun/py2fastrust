"""Captured deque indexed references retain Python get/RHS/set ordering."""
from dataclasses import dataclass
from .native_types import alternatives

@dataclass
class Indexed:
    owner:object
    index:object

class Indexes:
    def __init__(self,deques):self.deques=deques;self.model=deques.model;self.reads={}
    def owns(self,owner):
        from .native_classes import shape
        kinds=alternatives(shape(owner))
        return bool(kinds)and all(self.deques.owns(kind)for kind in kinds)
    def _index(self,node,index):
        from .native_classes import shape,domain,ClassUnsupported
        sealed={'int','bool','int_bool','none','float','str','bytes','list','tuple','tuple_sequence','range','function','dict','set','dict_view','deque','iterator','generator','globals_dict'}
        for kind in alternatives(shape(index)):
            if kind is not None and domain(kind)not in sealed:
                raise ClassUnsupported(node,'this deque index needs its user __index__ conversion; the typed builtin-index adapter does not implement that special-method protocol',types=(('index',kind),),proof='deque integer index conversion')
    def analyze_read(self,plan,node,owner,index):
        if not self.owns(owner):return None
        from .native_classes import shape
        self._index(node,index)
        result=self.model.cell(plan,node)
        for kind in alternatives(shape(owner)):self.deques._contribute(result,kind.record.element,node)
        self.reads[(plan.index,id(node))]=Indexed(owner,index)
        return result
    def analyze_store(self,plan,node,owner,index,value):
        if not self.owns(owner):return False
        from .native_classes import shape
        self._index(node,index)
        for kind in alternatives(shape(owner)):self.deques._contribute(kind.record.element,value,node)
        result=self.model.cell(plan,node)
        for kind in alternatives(shape(owner)):self.deques._contribute(result,kind.record.element,node)
        return True
    def captured_store(self,plan,node,value):
        site=self.reads.get((plan.index,id(node)))
        if site is None:return False
        return self.analyze_store(plan,node,site.owner,site.index,value)
    def analyze_delete(self,plan,node,environment):
        import ast
        if not isinstance(node,ast.Subscript)or isinstance(node.slice,ast.Slice):return False
        owner=self.model.expression(plan,node.value,environment)
        index=self.model.expression(plan,node.slice,environment)
        return self.analyze_read(plan,node,owner,index)is not None
    def _integer(self,emitter,node,index):
        from .native_classes import Expression
        from .native_unions import project
        from .native_class_builtins import _type_name
        def leaf(kind,text):
            value=Expression('('+text+').clone()',kind)
            if kind not in {'int','bool','int_bool'}:
                return emitter.at('Err::<isize,String>(format!("TypeError: sequence index must be integer, not \'{}\'",'+_type_name(emitter,value,node)+'))',node)
            number=emitter.number(value)
            wide='('+number+').to_i128()'if emitter.model.integer=='bigint'else'Some(('+number+')as i128)'
            return emitter.at('('+wide+').and_then(|value|isize::try_from(value).ok()).ok_or_else(||"IndexError: cannot fit \'int\' into an index-sized integer".to_owned())',node)
        return project(index.kind,index.code,leaf)
    def emit(self,emitter,node,owner,index,wanted,value=None,*,deleting=False):
        from .native_classes import Expression,shape
        from .native_unions import project
        def leaf(kind,text):
            handle,offset,read,position,result=(emitter.fresh()for _ in range(5))
            before='let '+handle+'=('+text+').clone();let '+offset+'='+self._integer(emitter,node,index)+';'
            before+='let '+('mut 'if value is not None or deleting else'')+read+'='+handle+'.'+('borrow_mut()'if value is not None or deleting else'borrow()')+';'
            before+='let '+position+'='+emitter.at('native_deque_index('+offset+','+read+'.len())',node)+';'
            if deleting:operation=read+'.values.remove('+position+')';raw='none'
            elif value is not None:operation=read+'.values['+position+']='+emitter.coerce(value,shape(kind.record.element),node);raw='none'
            else:operation=read+'.values['+position+'].clone()';raw=shape(kind.record.element)
            if deleting:
                return '{'+before+'let '+result+'='+operation+';drop('+read+');drop('+result+');()}'
            code=emitter.coerce(Expression(operation,raw),wanted,node)
            return '{'+before+'let '+result+'='+code+';'+result+'}'
        return Expression(project(owner.kind,owner.code,leaf),wanted)
    def emit_delete(self,emitter,node):
        import ast
        if not isinstance(node,ast.Subscript)or isinstance(node.slice,ast.Slice):return None
        from .native_classes import domain
        before,owner=emitter.capture(emitter.expression(node.value))
        if not all(domain(kind)=='deque'for kind in alternatives(owner.kind)):return None
        setup,index=emitter.capture(emitter.expression(node.slice))
        return before+setup+self.emit(emitter,node,owner,index,'none',deleting=True).code+';'
