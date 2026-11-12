"""Nonescaping scalar initialization can finish before shared handle allocation."""


class Registry:
    def __init__(self,model):
        self.owners=set()
        self.initializers={}
        from .native_copy_scalar_fields import selected as scalar_fields
        from .native_value_classes import selected as value_class
        from .native_packed_value_fields import selected as initialized
        from .native_namespace_read_places import lifetime_closed
        if not lifetime_closed(model):return
        for owner in model.classes.values():
            if (not owner.used or value_class(model,owner)
                    or not scalar_fields(model,owner)or not initialized(model,owner)):
                continue
            initializer=owner.methods.get('__init__')
            if initializer is None:continue
            # For a shared owner the initialized-field certificate separately
            # proved fresh canonical construction and no receiver publication,
            # method call, capture or preassignment field read in __init__.
            self.owners.add(owner.index)
            self.initializers[initializer.index]=(owner.index,initializer.runtime_parameters[0])


def prepare(model):model.scalar_constructor_data=Registry(model)


def selected(model,owner):
    return owner.index in getattr(getattr(model,'scalar_constructor_data',None),'owners',())


def receiver_type(model,plan,name):
    registry=getattr(model,'scalar_constructor_data',None)
    entry=None if registry is None else registry.initializers.get(plan.index)
    return ('ClassData_'+str(entry[0]))if entry is not None and entry[1]==name else None
