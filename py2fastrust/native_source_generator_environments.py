"""Concrete strong lexical environments owned by source-generator frames."""
from dataclasses import dataclass


@dataclass(frozen=True)
class FrameEnvironments:
    own:object
    parent:object


def layout(model,plan):
    lexical=model.lexical
    own=lexical.environments.get(lexical.scope(plan))
    parent=lexical.parent_scope(plan)if lexical.signature(plan)else None
    return FrameEnvironments(own,parent)


def prepare(emitter):
    stored=layout(emitter.model,emitter.plan)
    emitter.source_generator_environments=stored
    if stored.own is not None:
        # The original lexical binding is the sole runtime storage for these
        # names. Emitter discovery also reserves ordinary local placeholders;
        # none of those empty duplicates belongs in the suspended frame.
        emitter.slots={key:slot for key,slot in emitter.slots.items()
                       if key[0]not in stored.own.fields}


def own_expression(emitter,scope):
    stored=getattr(emitter,'source_generator_environments',None)
    if stored is not None and stored.own is not None and stored.own.scope==scope:
        return 'class_lexical_environment'
    return None


def captured_parameter(emitter,name):
    stored=emitter.source_generator_environments
    return stored.own is not None and name in stored.own.fields


def retained_kinds(model,plan):
    from .native_classes import shape
    stored=layout(model,plan);lexical=model.lexical;seen=set();result=[]
    scope=stored.own.scope if stored.own is not None else stored.parent
    while scope is not None and scope not in seen:
        seen.add(scope);environment=lexical.environments[scope]
        result.extend(shape(value)for value in environment.fields.values())
        result.extend(shape(value)for value in environment.defaults.values())
        scope=environment.parent
    return result


def frame_fields(emitter,fields,initial):
    stored=emitter.source_generator_environments;lexical=emitter.model.lexical
    if stored.own is not None:
        fields['lexical_environment']='std::rc::Rc<'+lexical.environment_type(stored.own.scope)+'>'
        initial['lexical_environment']='class_lexical_environment'
    elif stored.parent is not None:
        fields['lexical_parent']='std::rc::Rc<'+lexical.environment_type(stored.parent)+'>'
        initial['lexical_parent']='class_lexical_parent.clone()'


def factory_initialize(emitter):
    return emitter.model.lexical.initialize(emitter)


def resume_initialize(emitter):
    stored=emitter.source_generator_environments;code=''
    if stored.own is not None:
        code+='let class_lexical_environment=frame.lexical_environment.clone();'
        if stored.parent is not None:
            code+='let class_lexical_parent=class_lexical_environment.parent.clone();'
    elif stored.parent is not None:
        code+='let class_lexical_parent=frame.lexical_parent.clone();'
    return code


def lifetime_edges(model,record,edges):
    stored=layout(model,record.generator_plan)
    node=('iterator',record.index)
    if stored.own is not None:edges[node].add(('environment',stored.own.scope))
    elif stored.parent is not None:edges[node].add(('environment',stored.parent))
