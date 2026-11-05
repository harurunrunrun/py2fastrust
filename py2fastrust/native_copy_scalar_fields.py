"""Use independent Cell slots for proved Copy-only, untracked instance data.

Object and class-definition identities remain Rc handles. Mutable/reference
payloads and the cycle collector retain their existing RefCell object layout.
"""


def selected(model,owner):
    from .native_classes import shape
    if model.class_key(owner)in getattr(model,'gc_classes',()):return False
    kinds={'bool','float','none'}
    if model.integer in {'i64','i128'}:kinds.add('int')
    fields=(shape(field.cell)for field in owner.fields.values())
    return all(isinstance(kind,str)and kind in kinds for kind in fields)


def load(model,owner,receiver,index):
    from .native_initialized_owned_fields import selected as initialized
    if initialized(model,owner,index):return f'Some(({receiver}).borrow().field_{index}.clone())'
    from .native_constant_field_projection import read
    projected=read(model,owner,receiver,index)
    if projected is not None:return 'Some('+projected+')'
    from .native_packed_value_fields import selected as packed,raw
    if packed(model,owner):return 'Some('+raw(receiver,index)+')'
    operation='get()'if selected(model,owner)else'clone()'
    return f'({receiver}).borrow().field_{index}.{operation}'


def store(model,owner,receiver,index,value):
    from .native_initialized_owned_fields import selected as initialized
    if initialized(model,owner,index):return f'({receiver}).borrow_mut().field_{index}={value};'
    from .native_constant_field_projection import store as project_store
    projected=project_store(model,owner,receiver,index,value)
    if projected is not None:return projected
    from .native_packed_value_fields import selected as packed
    if packed(model,owner):return f'({receiver}).borrow().field_{index}.set({value});'
    if selected(model,owner):return f'({receiver}).borrow().field_{index}.set(Some({value}));'
    return f'({receiver}).borrow_mut().field_{index}=Some({value});'
