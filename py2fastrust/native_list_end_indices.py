"""Read exact builtin-list first/last literals without general index arithmetic."""
import ast


def method(index):
    if isinstance(index,ast.Constant)and type(index.value)is int and index.value==0:return 'first'
    if (isinstance(index,ast.UnaryOp)and isinstance(index.op,ast.USub)
            and isinstance(index.operand,ast.Constant)
            and type(index.operand.value)is int and index.operand.value==1):return 'last'
    return None


def result(values,operation,*,clone=True):
    leaf=f'({values}).{operation}()'+('.cloned()'if clone else'')
    return leaf+'.ok_or_else(||String::from("IndexError: list index out of range"))'


def class_get(emitter,node,owner,wanted=None):
    from .native_types import ListType
    if not isinstance(node,ast.Subscript)or not isinstance(owner.kind,ListType):return None
    operation=method(node.slice)
    if operation is None:return None
    from .native_classes import Expression
    guard,value=emitter.fresh(),emitter.fresh()
    # Drop the content borrow before NativeError mapping/propagation or any
    # later source argument/callback; only the static error String is built here.
    code=('{let '+value+'={let '+guard+'='+owner.code+'.borrow();'
          +result(guard,operation)+'};'+emitter.at(value,node)+'}')
    wanted=wanted or emitter.kind(node)
    from .native_list_positions import project_element
    return project_element(emitter,code,owner.kind.element,wanted,node)


def class_read(emitter,node):
    from .native_types import ListType
    if not isinstance(node,ast.Subscript)or method(node.slice)is None:return None
    kind=emitter.kind(node.value)
    if not isinstance(kind,ListType):return None
    from .native_classes import Expression
    from .native_list_access_regions import selected
    region=selected(emitter,node.value)
    if region is not None:
        code=emitter.at(result(region.checked(emitter,node.value),method(node.slice)),node)
        wanted=emitter.kind(node)
        from .native_list_positions import project_element
        return project_element(emitter,code,kind.element,wanted,node)
    setup,owner=emitter.capture(emitter.expression(node.value))
    value=class_get(emitter,node,owner)
    return Expression('{'+setup+value.code+'}',value.kind)
