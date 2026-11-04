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
    operation='get()'if selected(model,owner)else'clone()'
    return f'({receiver}).borrow().field_{index}.{operation}'


def store(model,owner,receiver,index,value):
    if selected(model,owner):return f'({receiver}).borrow().field_{index}.set(Some({value}));'
    return f'({receiver}).borrow_mut().field_{index}=Some({value});'
