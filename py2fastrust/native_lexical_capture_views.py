"""Exact strong free-cell views for closed original lambda bodies.

This first certificate covers direct lambda bodies defined in ordinary source
function frames. Ordinary sibling functions retain their environment ABI and
share the promoted cells. Genuine callable/object capture cycles remain guarded.
"""
import ast
from dataclasses import dataclass


@dataclass(frozen=True)
class CaptureView:
    definition:int
    cells:tuple

    @property
    def rust(self):return 'ClassLexicalCapture'+str(self.definition)


def _data(kind):
    from .native_types import ListType,SharedListType,TupleType,TupleSequenceType,NullableType,UnionType,EmptyType
    if isinstance(kind,EmptyType):return True
    if type(kind)in{ListType,SharedListType,TupleSequenceType}:return _data(kind.element)
    if type(kind)is TupleType:return all(_data(child)for child in kind.fields)
    if isinstance(kind,NullableType):return _data(kind.value)
    if isinstance(kind,UnionType):return all(_data(child)for child in kind.alternatives)
    return kind in {'int','bool','int_bool','float','complex','str','bytes','none','range'}


def prepare(lexical):
    from .native_classes import shape
    model=lexical.model;unit=model.unit
    views={};promoted=set()
    if unit is not None:
        bindings=tuple(model.iter_bindings())
        for definition in sorted(model.lambda_cells.active):
            plan=model.lambda_cells.plans[definition]
            scope=lexical.scope(plan);parent=lexical.parent_scope(plan)
            enclosing=lexical.environments.get(parent)
            if(enclosing is None or not isinstance(enclosing.plan.node,ast.FunctionDef)
                    or getattr(plan,'source_generator',None)is not None
                    or getattr(enclosing.plan,'source_generator',None)is not None
                    or scope in lexical.environments):continue
            if any(isinstance(node,(ast.Lambda,ast.GeneratorExp,ast.ListComp,ast.SetComp,ast.DictComp,ast.Yield,ast.YieldFrom))
                   for node in ast.walk(plan.node.body)):continue
            free={symbol.name for symbol in unit.scope_for(plan.node).symbols if symbol.has('free')}
            if not free:continue
            cells=set();matched=set();valid=True
            for row in bindings:
                if row.scope!=scope or row.name not in free:continue
                owner=lexical.environments.get(row.owner)
                if(row.role!='load' or owner is None or not isinstance(owner.plan.node,ast.FunctionDef)
                        or getattr(owner.plan,'source_generator',None)is not None
                        or row.name not in owner.fields or(row.owner,row.name)in lexical.definitions
                        or not _data(shape(owner.fields[row.name]))):
                    valid=False;break
                cells.add((row.owner,row.name));matched.add(row.name)
            if not valid or matched!=free:continue
            view=CaptureView(definition,tuple(sorted(cells)))
            views[definition]=view;promoted.update(cells)
    model.lexical_capture_views=views
    model.lexical_shared_capture_cells=frozenset(promoted)


def selected(model,plan):
    if model.unit is None:return None
    return getattr(model,'lexical_capture_views',{}).get(model.unit.ordinal(plan.node))


def shared(model,scope,name):return(scope,name)in getattr(model,'lexical_shared_capture_cells',())


def cell_node(scope,name):return('lexical_cell',scope,name)


def parent_type(model,plan):
    view=selected(model,plan)
    return None if view is None else view.rust


def _cell(emitter,scope,name):
    view=selected(emitter.model,emitter.plan)
    if view is not None:
        try:index=view.cells.index((scope,name))
        except ValueError:
            from .native_classes import ClassUnsupported
            raise ClassUnsupported(emitter.plan.node,'the selected free-cell view has no cell for this lexical binding',proof='complete original free-cell capture')from None
        context=getattr(emitter,'lexical_environment_override',None)or'class_lexical_parent'
        return '('+context+').cell_'+str(index)
    lexical=emitter.model.lexical
    owner=lexical.expression_environment(emitter,scope)
    index=sorted(lexical.environments[scope].fields).index(name)
    return '('+owner+').value_'+str(index)


def construct(emitter,plan):
    view=selected(emitter.model,plan)
    if view is None:return None
    fields=['cell_'+str(index)+':'+_cell(emitter,scope,name)+'.clone()'
            for index,(scope,name)in enumerate(view.cells)]
    return view.rust+'{'+','.join(fields)+'}'


def optional_read(emitter,scope,name):
    if selected(emitter.model,emitter.plan)is None:return None
    return 'class_lexical_capture_read(&('+_cell(emitter,scope,name)+'))'


def edges(model,definition):
    view=getattr(model,'lexical_capture_views',{}).get(definition)
    return None if view is None else{cell_node(scope,name)for scope,name in view.cells}


def runtime(model,emitter):
    from .native_classes import shape
    lexical=model.lexical;lines=[]
    for definition,view in sorted(getattr(model,'lexical_capture_views',{}).items()):
        fields=['cell_'+str(index)+':std::rc::Rc<std::cell::RefCell<Option<'
                +emitter.rust_type(shape(lexical.environments[scope].fields[name]))+'>>>'
                for index,(scope,name)in enumerate(view.cells)]
        lines.append('#[derive(Clone)]struct '+view.rust+'{'+','.join(fields)+'}')
    if lines:
        lines.append('fn class_lexical_capture_read<T:Clone>(cell:&std::rc::Rc<std::cell::RefCell<Option<T>>>)->Option<T>{cell.borrow().clone()}')
    return '\n'.join(lines)
