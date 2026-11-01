"""Per-execution nested function data, separate from its captured environment."""


def instanced(lexical,plan):return lexical.definition(plan)in lexical.repeated_definitions


def data_type(lexical,plan):return 'ClassFunctionData'+str(lexical.definition(plan))


def reference_type(lexical,plan):return 'ClassFunctionInstanceRef'+str(lexical.definition(plan))


def reference(lexical,emitter,plan,owner):
    definition=lexical.definition(plan)
    data='('+owner+').instance_'+str(definition)+'.borrow().clone().expect("function data initialized before binding")'
    return reference_type(lexical,plan)+'{environment:('+owner+').clone(),data:'+data+'}'


def emit_define(lexical,emitter,plan,owner,environment):
    from .native_classes import shape
    lines=[];fields=[];stores=[]
    for index,(name,expression)in enumerate(plan.defaults.items()):
        if name in plan.default_literals:continue
        before,value=emitter.capture(emitter.expression(expression));lines.append(before)
        encoded=emitter.coerce(value,shape(plan.default_cells[name]),expression)
        temporary=emitter.fresh();lines.append('let '+temporary+'='+encoded+';')
        fields.append('default_'+str(index)+':'+temporary)
        slot=sorted(owner.defaults).index((plan.index,name))
        stores.append('('+environment+').default_'+str(slot)+'.replace(Some('+temporary+'.clone()));')
    definition=lexical.definition(plan)
    data='std::rc::Rc::new('+data_type(lexical,plan)+'{'+','.join(fields)+'})'
    # All defaults finish before replacing the previous successful binding.
    lines+=stores
    lines.append('('+environment+').instance_'+str(definition)+'.replace(Some('+data+'));')
    lines.append('('+environment+').defined_'+str(definition)+'.set(true);')
    return ''.join(lines)


def runtime(lexical,emitter):
    from .native_classes import shape
    lines=[]
    for definition in sorted(lexical.repeated_definitions):
        plan=lexical.plans[definition];parent=lexical.parent_scope(plan)
        if not lexical.environments[parent].plan.reachable:continue
        fields=[]
        for index,name in enumerate(plan.defaults):
            if name not in plan.default_literals:fields.append('default_'+str(index)+':'+emitter.rust_type(shape(plan.default_cells[name])))
        data=data_type(lexical,plan)
        lines.append('struct '+data+'{'+','.join(fields)+'}')
        lines.append('#[derive(Clone)]struct '+reference_type(lexical,plan)+'{environment:std::rc::Rc<'+lexical.environment_type(parent)+'>,data:std::rc::Rc<'+data+'>}')
    return '\n'.join(lines)


def lifetime_edges(lexical,edges,targets):
    from .native_classes import shape
    for definition in lexical.repeated_definitions:
        plan=lexical.plans[definition];parent=lexical.parent_scope(plan)
        if not lexical.environments[parent].plan.reachable:continue
        node=('function_defaults',definition)
        edges[node]={target for cell in plan.default_cells.values()for target in targets(shape(cell))}
        edges.setdefault(('environment',parent),set()).add(node)
