"""Implicit lexical class cells from official binding-owner metadata.

A retained module generation owns each admitted class publication. Its private
cell is distinct from the replaceable public class-name binding and is filled
as soon as the actual class object exists. Callable module captures therefore
preserve the original lexical class even after global or receiver rebinding.
"""
import ast



def requires_namespace(unit):
    return any(binding.name=='__class__' and binding.scope!=binding.owner
               and unit.scopes[binding.owner].kind=='class'for binding in unit.bindings)


def registry(model):
    result=getattr(model,'source_class_cells',None)
    if result is None:
        result={};model.source_class_cells=result
    return result


def owner(model,node):
    if not isinstance(node,ast.Name)or node.id!='__class__':return None
    binding=model.unit.binding_for(node)
    if binding is None or binding.role!='load' or binding.name!='__class__':return None
    scope=model.unit.scopes[binding.owner]
    if scope.kind!='class' or binding.scope==binding.owner:return None
    namespace=getattr(model,'class_namespaces',None)
    selected=None if namespace is None else namespace.scopes.get(binding.owner)
    if selected is None:return None
    from .native_classes import ClassUnsupported
    # An official implicit free-variable reference must reach its original
    # class object; an explicit local/global spelling does not select this cell.
    if selected.node.decorator_list or selected.node.type_params:
        raise ClassUnsupported(node,'the implicit lexical __class__ cell needs class decorator/type-parameter publication semantics before that class construction can be admitted',proof='original implicit class-cell initialization')
    unit=model.unit
    defining=unit.binding_for(selected.node)
    scope=unit.scopes[defining.owner]if defining is not None else None
    while scope is not None and scope.kind=='class':scope=unit.scopes[scope.parent]
    if scope is None or scope.kind!='module':
        raise ClassUnsupported(node,'the implicit __class__ cell belongs to a repeated or function-local class definition; per-execution class-cell storage is not implemented',proof='once-per-defining-module class-cell ownership')
    for other in model.iter_bindings():
        if other.owner==binding.owner and other.name=='__class__' and other.role!='load':
            raise ClassUnsupported(node,'the implicit lexical __class__ cell is written or deleted; mutable nonlocal class-cell storage is not implemented',proof='immutable implicit class-cell binding')
    registry(model)[selected.index]=selected
    return selected



def validate(model):
    """Mutable implicit class cells need their own execution-time storage."""
    from .native_classes import ClassUnsupported
    nodes={model.unit.ordinal(node):node for node in model.iter_nodes()}
    for binding in model.iter_bindings():
        if (binding.name=='__class__' and binding.role not in {'load','nonlocal'}
                and binding.scope!=binding.owner and model.unit.scopes[binding.owner].kind=='class'):
            node=nodes.get(binding.node,model.tree)
            raise ClassUnsupported(node,'writing or deleting the implicit lexical __class__ cell requires mutable nonlocal class-cell storage, which is not implemented',proof='immutable implicit class-cell binding')


def analyze(model,plan,node):
    selected=owner(model,node)
    if selected is None:return None
    from .native_module_linking import ClassReferenceType
    result=model.cell(plan,node,ClassReferenceType(selected.index))
    return model.remember(plan,node,result)


def emit(emitter,node):
    selected=owner(emitter.model,node)
    if selected is None:return None
    from .native_classes import Expression
    from .native_module_linking import ClassReferenceType
    field='class_lexical_cell_'+str(selected.index)
    message='NameError: cannot access free variable \'__class__\' where it is not associated with a value in enclosing scope'
    from .native import _string
    code='{let value=class_scope.globals.borrow().'+field+'.clone();value.ok_or_else(||'+_string(message)+'.to_owned())}'
    return Expression(emitter.at(code,node),ClassReferenceType(selected.index))


def publication(model,selected,created):
    if selected.index not in registry(model):return ''
    return 'class_scope.globals.borrow_mut().class_lexical_cell_'+str(selected.index)+'=Some('+created+'.clone());'


def layout(model):
    numbers=sorted(registry(model))
    fields=''.join('class_lexical_cell_'+str(index)+':Option<ClassClassRef>,'for index in numbers)
    initial=''.join('class_lexical_cell_'+str(index)+':None,'for index in numbers)
    return fields,initial
