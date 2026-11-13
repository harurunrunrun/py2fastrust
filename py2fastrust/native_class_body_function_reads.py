"""Publication proofs for actual module-function reads in source class bodies."""
import ast


def _inert(node):
    """No invocation, protocol conversion, or namespace store before a read."""
    if node is None or isinstance(node,(ast.Name,ast.Constant)):return True
    if isinstance(node,(ast.List,ast.Tuple)):
        return all(_inert(child)for child in node.elts)
    return False


def _statement_inert(node):
    if isinstance(node,ast.Pass):return True
    if isinstance(node,ast.Expr):return _inert(node.value)
    if isinstance(node,ast.Assign):
        return all(isinstance(target,ast.Name)for target in node.targets)and _inert(node.value)
    if isinstance(node,ast.FunctionDef):
        return (not node.decorator_list and not node.type_params
                and all(_inert(value)for value in node.args.defaults+node.args.kw_defaults)
                and not node.returns and not any(argument.annotation for argument in
                    node.args.posonlyargs+node.args.args+node.args.kwonlyargs
                    +([node.args.vararg]if node.args.vararg else[])
                    +([node.args.kwarg]if node.args.kwarg else[])))
    return False


def _expression_prefix(node,target):
    if node is target:return True
    if isinstance(node,(ast.List,ast.Tuple)):
        values=node.elts
    elif isinstance(node,ast.Call):
        values=[node.func]+node.args+[keyword.value for keyword in node.keywords]
    elif isinstance(node,ast.BinOp):values=[node.left,node.right]
    elif isinstance(node,ast.UnaryOp):values=[node.operand]
    else:return False
    for value in values:
        if any(child is target for child in ast.walk(value)):
            return _expression_prefix(value,target)
        if not _inert(value):return False
    return False


def _class_prefix(owner,node):
    for member in owner.node.body:
        if any(child is node for child in ast.walk(member)):
            if isinstance(member,(ast.Assign,ast.Expr)):
                return _expression_prefix(member.value,node)
            return False
        if not _statement_inert(member):return False
    return False


def _dominates_class(model,plan,event):
    origin=model.unit.original_unit(event)
    owner=plan.class_body
    statements=origin.tree.body
    return (model.unit.original_unit(owner.node)is origin and event in statements
            and owner.node in statements and statements.index(event)<statements.index(owner.node))


def _published_prefix(model,plan,node,event,name,binding):
    """An original direct module event dominates this particular class read.

    All preceding execution after publication is callback-free. Inner function
    bodies and later stores can therefore remain mutable without being mistaken
    for an already executed write. A namespace is never frozen after this read.
    """
    origin=model.unit.original_unit(event)
    owner=plan.class_body
    if model.unit.original_unit(owner.node)is not origin:return False
    statements=origin.tree.body
    if event not in statements or owner.node not in statements:return False
    before,after=statements.index(event),statements.index(owner.node)
    if before>=after:return False
    if any(not _statement_inert(statement)for statement in statements[before+1:after]):return False
    # An inert assignment can still replace this module binding. Official
    # binding rows distinguish real module stores from unrelated class locals.
    ordinals={model.unit.ordinal(child)for statement in statements[before+1:after]
              for child in ast.walk(statement)if id(child)in model.unit.node_ordinals}
    if any(row.owner==binding.owner and row.name==name and row.role not in {'load','parameter'}
           and row.node in ordinals and row.scope==binding.owner for row in model.unit.bindings):return False
    return _class_prefix(owner,node)


def _effects_closed(model,provider,name):
    if model.namespace.globals_observed:return False
    # Unknown namespace/reflection access is a conservative effect barrier.
    # Presence does not assume a spelling is the canonical builtin; absence
    # rules out every admitted path to an unrecorded namespace writer.
    mutation={'globals','locals','vars','dir','getattr','setattr','delattr','eval','exec','compile','__import__','__builtins__','__getattribute__','__getattr__','attrgetter','methodcaller'}
    metadata={'__dict__','__globals__','f_globals','f_locals','tb_frame'}
    spelling=provider.spelling(name)
    for original in model.iter_nodes():
        if isinstance(original,ast.Name)and original.id in mutation:return False
        if isinstance(original,ast.alias)and original.name.split('.')[-1]in mutation|metadata:return False
        if isinstance(original,(ast.FunctionDef,ast.AsyncFunctionDef))and original.name in mutation:return False
        if isinstance(original,ast.Attribute):
            if original.attr in mutation|metadata:return False
            if original.attr==spelling and isinstance(original.ctx,(ast.Store,ast.Del)):return False
    return True


def _is_unbinding(row,nodes):
    return row.role=='delete'or isinstance(nodes.get(row.node),ast.ExceptHandler)


def _unbinding_can_execute(model,row):
    """Only a closed, entirely unreferenced module function is unreachable.

    Negative reachability does not use provisional call edges or frame flags.
    The original all-unit binding/reference ledger must exclude every way to
    obtain this ordinary function, including imported and member references.
    """
    unit=model.unit
    candidates=[child for child in model.iter_nodes()if isinstance(child,ast.FunctionDef)
                and unit.scope_for(child).ordinal==row.scope]
    if len(candidates)!=1:return True
    function=candidates[0]
    origin=unit.original_unit(function)if hasattr(unit,'original_unit')else unit
    if function not in origin.tree.body or function.decorator_list or function.type_params:return True
    if function.name.startswith('__')or function.name.endswith('__'):return True
    # Annotated definitions can publish additional lazy metadata closures.
    args=function.args
    if function.returns or any(argument.annotation for argument in
            args.posonlyargs+args.args+args.kwonlyargs
            +([args.vararg]if args.vararg else[])+([args.kwarg]if args.kwarg else[])):return True
    definition=model.namespace.owners.get(unit.ordinal(function))
    if definition is None or not model.module_owner(definition.owner):return True
    if any(binding.owner==definition.owner and binding.name==definition.name and binding.role=='load'
           for binding in unit.bindings):return True
    for child in model.iter_nodes():
        if isinstance(child,ast.Name)and isinstance(child.ctx,ast.Load)and child.id==function.name:
            # Lazy annotation/type-parameter syntax can retain an original
            # reference without an executable binding row. It is not a proof
            # of unrelated ownership, so keep this function reachable.
            if unit.ordinal(child)not in model.namespace.owners:return True
        if isinstance(child,ast.Attribute)and child.attr==function.name:return True
        if isinstance(child,ast.ImportFrom):
            if any(alias.name=='*'for alias in child.names):return True
            imports=getattr(unit,'import_bindings',None)
            if imports is None:
                # An unlinked SourceUnit admits only its resolved native
                # modules. User module exports require the linked ledger.
                if child.module not in getattr(unit,'native_imports',()):return True
            elif any(binding.module==origin.name and binding.exported_name==function.name
                     for binding in imports(child)):return True
    return False


def read(provider,plan,node):
    from .native_classes import shape
    from .native_aot_callables import AotFunctionType
    model=provider.model
    if model.unit is None or plan.class_body is None or not isinstance(node,ast.Name):return None
    name=model.resolved_name(plan,node)
    if provider.spelling(name)not in model.namespace.builtin_names:return None
    binding=model.namespace.owners.get(model.unit.ordinal(node))
    if binding is None or not model.module_owner(binding.owner):return None
    if not _effects_closed(model,provider,name):return None
    writes=[row for row in model.unit.bindings if row.owner==binding.owner and row.name==name
            and row.role not in {'load','parameter'}]
    sources=model.namespace.incoming.get(name,{})
    direct=provider.owns_function(plan,node)
    if direct:
        if name not in(plan.visible_definitions or()):return None
        targets=model.function_versions(name)
        published=[target for target in targets if _dominates_class(model,plan,target.node)]
        if not published and len(targets)!=1:return None
        target=published[-1]if published else targets[0]
        definition=provider.definition(target)
        event=target.node
        value=provider.definition_values[definition]
        expected=('definition',definition)
        immutable=(name not in provider.mutable_names and name not in provider.versioned_names
                   and len(writes)==1 and writes[0].role=='definition'and writes[0].node==definition
                   and expected in sources
                   and all(key in {expected,('builtin',name)}for key in sources))
        if not immutable:
            # Initial publication proves binding presence, not its later
            # identity. Keep every actual producer, including assignments of
            # builtin objects; omit only the synthetic missing-name fallback.
            # Exception aliases have an implicit cleanup not recorded as Del.
            nodes={model.unit.ordinal(child):child for child in model.iter_nodes()}
            unbinding=any(_is_unbinding(row,nodes)and _unbinding_can_execute(model,row)for row in writes)
            if not unbinding and published:
                from .native_constraints import Variable
                actual=[cell for key,cell in sources.items()if key!=('builtin',name)]
                kind=model.namespace.value_kind(Variable(('native_class_initialized',plan.index,name),'value'),actual)
                if kind is None:return None
                value=model.namespace.representation(kind,actual,node)
            elif not _published_prefix(model,plan,node,event,name,binding):return None
    else:
        # A direct, unconditional original module store with no competing
        # writer proves presence, independently of its final payload kind.
        # Retain that real producer, including pending return constraints,
        # callable captures, actual None and noncallable alternatives.
        if len(writes)!=1 or writes[0].role!='store':return None
        store=writes[0].node
        if store not in sources or any(key not in {store,('builtin',name)}for key in sources):return None
        value=sources[store]
        origin=model.unit.original_unit(node)
        event=next((statement for statement in origin.tree.body if isinstance(statement,ast.Assign)
                    and any(isinstance(target_node,ast.Name)and model.unit.ordinal(target_node)==store
                            for target_node in statement.targets)),None)
        if event is None or not _dominates_class(model,plan,event):return None
        # Publication is already proved even while the producer's return
        # constraints are pending. Do not invent a builtin call/result before
        # the original source function has reached its fair fixed point.
        kind=shape(value)
        definition=None
        if isinstance(kind,AotFunctionType):provider.used.update(kind.definitions)
    if direct:
        origin=model.unit.original_unit(target.node)
        if target.node not in origin.tree.body or target.node.decorator_list:return None
        if any(candidate.node.decorator_list for candidate in model.function_versions(name)):return None
    provider.require_binding(name,node)
    if definition is not None:provider.used.add(definition)
    provider.builtin_sites.pop((plan.index,id(node)),None)
    linked=getattr(provider,'linked_builtins',None)
    if linked is not None:linked.sites.pop((plan.index,id(node)),None)
    return model.flow_copy(value)
