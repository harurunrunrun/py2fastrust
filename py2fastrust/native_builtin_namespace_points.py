"""Prove an unsupported initial builtin value is overwritten before a load.

This is a source-point capability certificate, not a builtin implementation.
The generated lookup still reads the actual current namespace payload.
"""
import ast


def unsupported_initial(model,module,name):
    from .native_class_builtins import SUPPORTED
    key=model.unit.global_name(module.name,name)
    linker=model.module_linker
    return (module.native_adapter and module.name=='builtins'
            and name in model.namespace.builtin_names and name not in SUPPORTED
            and key not in linker.implicit_values and key not in linker.implicit_members)


def require_replacement(model,module,name,node,context):
    if not model.final or not unsupported_initial(model,module,name):return
    if context is not None and replaced(model,context[0],node,module,name):return
    from .native_classes import ClassUnsupported
    raise ClassUnsupported(node,
        f"lookup can observe the original builtins.{name} value before a proved namespace replacement; "
        "that original builtin object's native representation/call capability is not implemented. "
        "Observed later assignments do not prove replacement on every reaching path",
        proof='actual builtin namespace payload, initialization order and operation capability')


def replaced(model,plan,node,module,name):
    return replacement(model,plan,node,module,name) is not None


def replacement(model,plan,node,module,name):
    """A completed same-block store dominates this load without reentry."""
    from .native_classes import shape
    if model.namespace.globals_observed or getattr(model,'gc_classes',()):return None
    if any('__del__'in owner.methods for owner in model.classes.values()):return None
    # Replacing an otherwise pure name can release a suspended frame and run
    # its source finally blocks.  Such lifetime effects are not pure stores.
    if any(isinstance(value,(ast.Yield,ast.YieldFrom,ast.GeneratorExp,ast.AsyncFunctionDef))
           for value in model.iter_nodes()):return None
    if any(getattr(shape(cell),'_native_namespace_view',False)for cell in model.records.values()):return None
    if any(model.display_name(row.name)=='__builtins__'for row in model.iter_bindings()):return None
    hooks={'__import__','__getattr__','__class__','__dict__','__setattr__'}
    if any(getattr(key,'module_name',None)==module.name and model.display_name(key)in hooks
           for key in model.namespace.incoming):return None
    parents=model.unit.parents
    statement=node
    while not isinstance(statement,ast.stmt):
        statement=parents.get(id(statement))
        if statement is None:return None
    parent=parents.get(id(statement))
    if parent is None:return None
    siblings=next((value for _,value in ast.iter_fields(parent)
                   if isinstance(value,list)and statement in value
                   and all(isinstance(item,ast.stmt)for item in value)),None)
    if siblings is None or not _prefix(model,plan,node,statement,module):return None
    for previous in reversed(siblings[:siblings.index(statement)]):
        if (isinstance(previous,ast.Assign)and len(previous.targets)==1
                and _slot(model,plan,previous.targets[0],module,name)):
            return model.records.get((plan.index,id(previous.value)))
        if not _statement(model,plan,previous):return None
    return None


def _slot(model,plan,target,module,name):
    from .native_classes import shape
    from .native_module_linking import ModuleType
    if not isinstance(target,ast.Attribute):return False
    cell=model.records.get((plan.index,id(target.value)))
    kind=None if cell is None else shape(cell)
    return (kind==ModuleType(module.number)
            and model.resolved_name(plan,target)==name and target.attr==name)


def _kind(model,plan,node):
    from .native_classes import shape
    cell=model.records.get((plan.index,id(node)))
    return None if cell is None else shape(cell)


def _pure(model,plan,node):
    if isinstance(node,ast.Constant):return True
    if isinstance(node,ast.Name):return isinstance(node.ctx,ast.Load)
    if isinstance(node,(ast.Tuple,ast.List)):
        return all(_pure(model,plan,value)for value in node.elts)
    if isinstance(node,ast.Attribute):
        from .native_module_linking import ModuleType
        kind=_kind(model,plan,node.value)
        if not isinstance(kind,ModuleType)or node.attr.startswith('__'):return False
        module=model.module_linker.by_number[kind.number]
        hook=model.unit.global_name(module.name,'__getattr__')
        return hook not in model.namespace.incoming and _pure(model,plan,node.value)
    from .native_scalar_effects import scalar_rhs
    return scalar_rhs(node,lambda value:_kind(model,plan,value))


def _statement(model,plan,node):
    if isinstance(node,ast.Pass):return True
    if isinstance(node,ast.Assign):
        return all(isinstance(target,ast.Name)or isinstance(target,ast.Attribute)and _pure(model,plan,target)
                   for target in node.targets)and _pure(model,plan,node.value)
    if isinstance(node,ast.Delete):
        return all(isinstance(target,ast.Name)for target in node.targets)
    if isinstance(node,ast.FunctionDef):
        return (not node.decorator_list and not node.type_params and node.returns is None
                and all(argument.annotation is None for argument in (*node.args.posonlyargs,*node.args.args,*node.args.kwonlyargs))
                and node.args.vararg is None and node.args.kwarg is None
                and all(value is None or _pure(model,plan,value)for value in (*node.args.defaults,*node.args.kw_defaults)))
    if not isinstance(node,ast.Expr):return False
    if _pure(model,plan,node.value):return True
    call=node.value
    if not isinstance(call,ast.Call):return False
    from .native_physical_list_builtins import static_builtin
    if not static_builtin(model,plan,call.func,'print'):return False
    values=[*call.args,*(keyword.value for keyword in call.keywords)]
    return (all(not isinstance(value,ast.Starred)and _pure(model,plan,value)
                and _kind(model,plan,value)in {'int','bool','int_bool','float','str','bytes','none'}for value in values)
            and all(keyword.arg is not None for keyword in call.keywords))


def _prefix(model,plan,node,statement,module):
    """Only operations evaluated before the actual lookup can invalidate it."""
    if isinstance(node,ast.Attribute)and not _pure(model,plan,node.value):return False
    if isinstance(statement,ast.ImportFrom):
        bindings=model.unit.import_bindings(statement)
        return bool(bindings)and all(binding.module==module.name for binding in bindings)
    if not isinstance(statement,(ast.Expr,ast.Assign,ast.AnnAssign,ast.Return)):return False
    current=node
    parents=model.unit.parents
    while (parent:=parents.get(id(current)))is not statement:
        if parent is None:return False
        previous=[]
        if isinstance(parent,ast.Call):
            if current is parent.func:pass
            elif current in parent.args:previous=[parent.func,*parent.args[:parent.args.index(current)]]
            elif current in parent.keywords:
                previous=[parent.func,*parent.args,*(keyword.value for keyword in parent.keywords[:parent.keywords.index(current)])]
            else:return False
        elif isinstance(parent,ast.keyword):
            if current is not parent.value:return False
        elif isinstance(parent,(ast.Tuple,ast.List)):
            if current not in parent.elts:return False
            previous=parent.elts[:parent.elts.index(current)]
        elif isinstance(parent,ast.BinOp):
            if current is parent.right:previous=[parent.left]
            elif current is not parent.left:return False
        elif isinstance(parent,ast.UnaryOp):
            if current is not parent.operand:return False
        elif isinstance(parent,ast.Attribute):
            if current is not parent.value:return False
        elif isinstance(parent,ast.Subscript):
            if current is parent.slice:previous=[parent.value]
            elif current is not parent.value:return False
        else:return False
        if not all(_pure(model,plan,value)for value in previous):return False
        current=parent
    return current is statement.value
