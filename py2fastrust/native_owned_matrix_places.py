"""Recursive physical vectors for private, structurally fresh local matrices.

The certificate belongs to an official binding, not to semantic ListType.
Every intermediate row is private and fixed in length/identity after publish.
"""
import ast
from dataclasses import dataclass

from .native_types import ListType
from .references import BuiltinIdentity


SCALARS=frozenset({'int','bool','float','str','bytes','none'})
INDICES=frozenset({'int','bool','int_bool'})


@dataclass(frozen=True)
class Tree:
    kind: object
    child: object=None

    @property
    def depth(self):return 0 if self.child is None else 1+self.child.depth


@dataclass(frozen=True)
class Matrix:
    local: object
    tree: Tree

    @property
    def name(self):return self.local.name

    @property
    def kind(self):return self.local.kind


def tree(kind):
    if isinstance(kind,ListType):
        child=tree(kind.element)
        return Tree(kind,child)if child is not None else None
    return Tree(kind)if kind in SCALARS else None


def split(node):
    indices=[]
    while isinstance(node,ast.Subscript):
        indices.append(node);node=node.value
    return node,tuple(reversed(indices))


def repeated(node):
    if not isinstance(node,ast.BinOp)or not isinstance(node.op,ast.Mult):return None
    if isinstance(node.left,ast.List):return node.left,node.right,False
    if isinstance(node.right,ast.List):return node.right,node.left,True
    return None


def fresh(emitter,node,layout):
    if emitter.kind(node)!=layout.kind:return False
    if layout.child is None:return True
    if isinstance(node,ast.List):
        return all(not isinstance(child,ast.Starred)and fresh(emitter,child,layout.child)for child in node.elts)
    if isinstance(node,ast.ListComp):
        return ((emitter.plan.index,id(node))in emitter.model.comprehensions
                and fresh(emitter,node.elt,layout.child))
    repeat=repeated(node)
    if repeat is not None and layout.child.child is None:
        literal,count,_=repeat
        return emitter.kind(count)in INDICES and fresh(emitter,literal,layout)
    return False


def prepare(emitter,candidates):
    from .native_owned_local_lists import static_builtin
    model,plan=emitter.model,emitter.plan
    unit=model.unit
    if not candidates:return {}
    parents={id(child):node for node in ast.walk(plan.node)for child in ast.iter_child_nodes(node)}
    nodes={ordinal:node for node in ast.walk(plan.node)
           if(ordinal:=unit.node_ordinals.get(id(node)))is not None}
    scope=model.lexical.scope(plan)
    result={}
    for name,local in candidates.items():
        layout=tree(local.kind)
        if layout is None or layout.depth<2 or len(local.allocations)!=1:continue
        valid=True
        for binding in unit.bindings:
            if binding.owner!=scope or binding.name!=local.binding[1]or binding.node not in nodes:continue
            node=nodes[binding.node]
            parent=parents.get(id(node))
            if binding.role=='store':
                if not isinstance(parent,(ast.Assign,ast.AnnAssign))or not fresh(emitter,parent.value,layout):
                    valid=False;break
            elif binding.role=='load':
                end=node
                while isinstance(parents.get(id(end)),ast.Subscript)and parents[id(end)].value is end:
                    end=parents[id(end)]
                _,indices=split(end)
                if any(isinstance(index.slice,ast.Slice)or emitter.kind(index.slice)not in INDICES for index in indices):
                    valid=False;break
                consumer=parents.get(id(end))
                length=(isinstance(consumer,ast.Call)and consumer.args==[end]and not consumer.keywords
                        and static_builtin(emitter,consumer.func,'len'))
                # A full-depth scalar read/store never exposes a row. A length
                # is also safe, including scalar len handled by the old path.
                if len(indices)==layout.depth and not isinstance(end.ctx,ast.Del):continue
                if length and len(indices)<layout.depth:continue
                valid=False;break
            else:valid=False;break
        if valid:result[name]=Matrix(local,layout)
    return result


def selected(emitter,node):
    if not isinstance(node,ast.Name)or not getattr(emitter,'owned_matrices',None):return None
    unit=emitter.model.unit
    if id(node)not in unit.node_ordinals:return None
    binding=emitter.model.lexical.binding(node)
    if binding is None or binding.owner!=emitter.model.lexical.scope(emitter.plan):return None
    return emitter.owned_matrices.get(emitter.model.resolved_name(emitter.plan,node))


def physical_type(emitter,layout):
    return emitter.rust_type(layout.kind)if layout.child is None else 'Vec<'+physical_type(emitter,layout.child)+'>'


def checked(emitter,matrix,node,mutable=False):
    from .native_owned_local_lists import checked as check
    return check(emitter,matrix.local,node,mutable)


def allocate(emitter,node,layout):
    from .native_classes import Expression
    if layout.child is None:return emitter.expression(node)
    if isinstance(node,ast.List):
        # Capture every original element before publication of the root slot.
        before=[];values=[]
        for child in node.elts:
            setup,value=emitter.capture(allocate(emitter,child,layout.child))
            before.append(setup)
            values.append(emitter.coerce(value,layout.child.kind,child)if layout.child.child is None else value.code)
        code='vec!['+','.join(values)+']'if values else '<'+physical_type(emitter,layout)+'>::new()'
        return Expression('{'+''.join(before)+code+'}',layout.kind)
    if isinstance(node,ast.ListComp):
        from .native_class_comprehensions import Collector,emit
        def append(g,result,semantic):
            setup,value=g.capture(allocate(g,semantic.element,layout.child))
            reserve=g.at(f'{result}.try_reserve(1).map_err(|_|"MemoryError: cannot allocate list".to_owned())',node)
            valuecode=g.coerce(value,layout.child.kind,semantic.element)if layout.child.child is None else value.code
            return setup+reserve+';'+f'{result}.push({valuecode});'
        collector=Collector(lambda g,result,wanted:f'let mut {result}:{physical_type(g,layout)}=Vec::new();',
                            append,lambda g,result,wanted:result)
        return emit(emitter,node,collector=collector,wanted=layout.kind)
    literal,count,reverse=repeated(node)
    if reverse:
        before,amount=emitter.capture(emitter.expression(count))
        after,values=emitter.capture(allocate(emitter,literal,layout))
    else:
        before,values=emitter.capture(allocate(emitter,literal,layout))
        after,amount=emitter.capture(emitter.expression(count))
    emitter.model.owned_list_repetition=True
    code=emitter.at(f'class_owned_list_repeat(&{values.code},&({emitter.number(amount)}))',node)
    return Expression('{'+before+after+code+'}',layout.kind)


def statement(emitter,node):
    if isinstance(node,ast.Assign)and len(node.targets)==1:target=node.targets[0]
    elif isinstance(node,ast.AnnAssign)and node.value is not None:target=node.target
    else:return None
    matrix=selected(emitter,target)
    if matrix is None:return None
    value=allocate(emitter,node.value,matrix.tree)
    return f'{emitter.slot(matrix.name,matrix.kind)}=Some({value.code});'


def _path(emitter,matrix,indices,node,mutable=False):
    root=checked(emitter,matrix,node,mutable)
    return '('+root+')'+''.join('['+offset+']'for offset in indices)


def prefix(emitter,matrix,root,indices):
    # Normalize/check each prefix immediately, before the next source index.
    before=checked(emitter,matrix,root)+';'
    offsets=[]
    for index in indices:
        setup,value=emitter.capture(emitter.expression(index.slice))
        offset=emitter.fresh()
        length='('+_path(emitter,matrix,offsets,root)+').len()'
        normalized=emitter.at(f'class_index(&({emitter.number(value)}),{length})',index)
        before+=setup+f'let {offset}={normalized};'
        offsets.append(offset)
    return before,tuple(offsets)


def reference(emitter,node):
    if not isinstance(node,ast.Subscript):return None
    root,indices=split(node)
    matrix=selected(emitter,root)
    if matrix is None or len(indices)!=matrix.tree.depth:return None
    before,offsets=prefix(emitter,matrix,root,indices[:-1])
    setup,index=emitter.capture(emitter.expression(indices[-1].slice))
    return before+setup,('owned_matrix',matrix,root,offsets,index,emitter.kind(node))


def load(emitter,reference,node,kind=None):
    from .native_classes import Expression
    _,matrix,root,offsets,index,element=reference
    owner=emitter.fresh();offset=emitter.fresh()
    value=_path(emitter,matrix,offsets,root)
    normalized=emitter.at(f'class_index(&({emitter.number(index)}),{owner}.len())',node)
    code='{'+f'let {owner}=&{value};let {offset}={normalized};{owner}[{offset}].clone()'+'}'
    leaf=matrix.tree
    while leaf.child is not None:leaf=leaf.child
    return Expression(emitter.coerce(Expression(code,leaf.kind),kind or element,node),kind or element)


def store(emitter,reference,value,node):
    from .native_classes import Expression
    _,matrix,root,offsets,index,_=reference
    layout=matrix.tree
    while layout.child is not None:layout=layout.child
    before,captured=emitter.capture(value)
    # Coercion can execute source protocols; finish it before taking a loan.
    more,captured=emitter.capture(Expression(emitter.coerce(captured,layout.kind,node),layout.kind))
    owner=emitter.fresh();offset=emitter.fresh()
    destination=_path(emitter,matrix,offsets,root,True)
    normalized=emitter.at(f'class_index(&({emitter.number(index)}),{owner}.len()).map_err(|_|"IndexError: list assignment index out of range".to_owned())',node)
    return '{'+before+more+f'let {owner}=&mut {destination};let {offset}={normalized};{owner}[{offset}]={captured.code};'+'}'


def read(emitter,node):
    from .native_classes import Expression
    from .native_owned_local_lists import static_builtin
    indexed=reference(emitter,node)
    if indexed is not None:
        before,place=indexed
        return Expression('{'+before+load(emitter,place,node).code+'}',emitter.kind(node))
    if (isinstance(node,ast.Call)and len(node.args)==1 and not node.keywords
            and static_builtin(emitter,node.func,'len')):
        root,indices=split(node.args[0])
        matrix=selected(emitter,root)
        if matrix is not None and len(indices)<matrix.tree.depth:
            before,offsets=prefix(emitter,matrix,root,indices)
            value=_path(emitter,matrix,offsets,root)
            return Expression('{'+before+f'class_from_usize(({value}).len())'+'}','int')
    return None


def requires_frames(unit,analysis):
    """Positive original-binding certificate, before either emitter runs.

    All reached argument contexts must agree on the candidate carrier. This
    intentionally leaves polymorphic ordinary specializations on their path.
    The frame model independently rechecks the physical ownership certificate.
    """
    from types import SimpleNamespace
    from .native_constraints import canonical_kind
    from .references import resolve_static_callable
    nodes={unit.ordinal(node):node for node in ast.walk(unit.tree)}
    parents={id(child):node for node in ast.walk(unit.tree)for child in ast.iter_child_nodes(node)}
    binding_at={binding.node:binding for binding in unit.bindings}
    module_bound=frozenset(binding.name for binding in unit.bindings
        if unit.is_module_scope(binding.owner)and binding.role not in {'load','parameter'})
    observers={'locals','eval','exec','compile','vars','_getframe','settrace','setprofile'}
    # An observer reached indirectly is just as relevant as its source name.
    for facts in analysis.scopes.values():
        for call in facts.calls.values():
            identity=call.identity
            if identity.unknown or identity.unbound or not identity.alternatives:return False
            if any(getattr(part,'name',None)in observers for part in identity.alternatives):return False

    contexts={}
    for(definition,_),facts in analysis.scopes.items():
        if definition is not None:contexts.setdefault(definition,[]).append(facts)
    for definition,scopes in contexts.items():
        function=nodes[definition]
        if not isinstance(function,(ast.FunctionDef,ast.AsyncFunctionDef)):continue
        scope=unit.scope_for(function).ordinal
        if unit.scopes[scope].kind!='function':continue
        groups={}
        for binding in unit.bindings:
            if binding.owner==scope:groups.setdefault(binding.name,[]).append(binding)
        def static_length(call):
            if not isinstance(call.func,ast.Name):return False
            binding=binding_at.get(unit.ordinal(call.func))
            if binding is None or not unit.is_module_scope(binding.owner):return False
            return resolve_static_callable(call.func,{},local_names=groups,
                global_bound_names=module_bound,name_for=unit.name_for,
                function_scope=True)==BuiltinIdentity('len')
        for bindings in groups.values():
            stores=[binding for binding in bindings if binding.role=='store']
            if len(stores)!=1 or any(binding.role not in {'store','load'}for binding in bindings):continue
            target=nodes[stores[0].node]
            assignment=parents.get(id(target))
            if (not isinstance(target,ast.Name)or not isinstance(assignment,(ast.Assign,ast.AnnAssign))
                    or isinstance(assignment,ast.Assign)and assignment.targets!=[target]
                    or assignment.value is None):continue
            captured=False
            for binding in bindings:
                current=binding.scope
                while unit.scopes[current].kind=='comprehension':current=unit.scopes[current].parent
                if current!=scope:captured=True;break
            if captured:continue
            kinds={canonical_kind(facts.expressions.get(unit.ordinal(assignment.value)))for facts in scopes}
            if len(kinds)!=1:continue
            kind=next(iter(kinds))
            layout=tree(kind)
            if layout is None or layout.depth<2:continue
            valid=True
            for facts in scopes:
                def kind_of(node):
                    return canonical_kind(facts.expressions.get(unit.ordinal(node)))
                def identity(node):
                    call=facts.calls.get(unit.ordinal(node))
                    if call is None or call.identity.unknown or call.identity.unbound:return None
                    values=call.identity.alternatives
                    return next(iter(values))if len(values)==1 else None
                # Reuse structural constructor validation with reached kinds;
                # this is analysis metadata, never a synthetic source class.
                proof=SimpleNamespace(kind=kind_of,plan=SimpleNamespace(index=0),
                    model=SimpleNamespace(comprehensions={(0,id(node)):True for node in ast.walk(assignment.value)
                        if isinstance(node,ast.ListComp)and unit.ordinal(node)in facts.allocations}))
                if not fresh(proof,assignment.value,layout):valid=False;break
                for binding in bindings:
                    if binding.role!='load':continue
                    root=nodes[binding.node]
                    if not isinstance(root,ast.Name)or kind_of(root)!=kind:valid=False;break
                    end=root
                    while isinstance(parents.get(id(end)),ast.Subscript)and parents[id(end)].value is end:
                        end=parents[id(end)]
                    _,indices=split(end)
                    if any(isinstance(index.slice,ast.Slice)or kind_of(index.slice)not in INDICES for index in indices):
                        valid=False;break
                    consumer=parents.get(id(end))
                    length=(isinstance(consumer,ast.Call)and consumer.args==[end]and not consumer.keywords
                            and identity(consumer)==BuiltinIdentity('len')and static_length(consumer))
                    if len(indices)==layout.depth and not isinstance(end.ctx,ast.Del):continue
                    if length and len(indices)<layout.depth:continue
                    valid=False;break
                if not valid:break
            if valid:return True
    return False
