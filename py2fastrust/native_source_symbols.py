"""Map declared native source entry variants to their original solved plans.

An optimization ABI changes the physical symbol, not its source binding,
effects or call height. Consumers must still validate the emitted Rust shape.
Constructor wrappers stay separate from source function entry ranks.
"""


def function_plans(model):
    plans = {plan.index: plan for plan in getattr(model, 'plans', ()) if plan.reachable}
    result = {'class_function_' + str(index): plan for index, plan in plans.items()}
    result.update(getattr(getattr(model,'scalar_data_results',None),'emitted',{}))
    state = getattr(model, 'source_state', None)
    if state is None or not state.bridges:
        return result
    for index, abi in state.abis.items():
        if plans.get(index) is abi.plan:
            result['class_state_function_' + str(index)] = abi.plan
    for index, producer in state.producers.items():
        if plans.get(index) is producer.plan:
            result['class_state_enter_' + str(index)] = producer.plan
    return result


def constructor_names(model):
    state = getattr(model, 'source_state', None)
    result = set()
    for owner in getattr(model, 'classes', {}).values():
        if not owner.used:
            continue
        result.add('class_construct_' + str(owner.index))
        from .native_scalar_constructor_data import selected as data_constructor
        data=data_constructor(model,owner)
        if data:result.add('class_build_'+str(owner.index))
        initializer = owner.methods.get('__init__')
        if (state is not None and state.bridges and initializer is not None
                and initializer.index in state.abis
                and state.abis[initializer.index].plan is initializer):
            result.add('class_state_construct_' + str(owner.index))
            if data:result.add('class_state_build_'+str(owner.index))
    return result
