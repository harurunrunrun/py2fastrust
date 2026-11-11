"""Initialize retained class metadata at its proved single publication point."""


def prepare(model):
    state = getattr(model, 'source_state', None)
    selected = set()
    model.published_metadata = selected
    if state is None or state.barrier is not None:
        return
    from .native_source_class_bindings import publication_closed
    from .native_value_classes import selected as value_class
    for owner in model.classes.values():
        if owner.used and value_class(model, owner) and publication_closed(state, owner):
            selected.add(owner.index)


def publication(emitter, owner, reference):
    if owner.index not in getattr(emitter.model, 'published_metadata', ()):
        return ''
    return 'class_publish_metadata_' + str(owner.index) + '(&' + reference + ');'


def layout(model, owner):
    if owner.index not in getattr(model, 'published_metadata', ()):
        return None
    index = str(owner.index)
    return ('class_definition:ClassValueMetadata_' + index,
            'class_definition:ClassValueMetadata_' + index,
            RUNTIME.replace('__INDEX__', index))


RUNTIME = r'''
#[derive(Clone)]
struct ClassValueMetadata___INDEX__;
impl std::ops::Deref for ClassValueMetadata___INDEX__ {
 type Target=ClassClassRef;
 fn deref(&self)->&ClassClassRef {
  CLASS_VALUE_METADATA___INDEX__.with(|slot|*slot.get().expect("published class metadata"))
 }
}
impl ClassValueMetadata___INDEX__ {
 fn clone(&self)->ClassClassRef {Rc::clone(std::ops::Deref::deref(self))}
}
thread_local! {
 static CLASS_VALUE_METADATA___INDEX__:std::cell::OnceCell<&'static ClassClassRef>=std::cell::OnceCell::new();
}
fn class_publish_metadata___INDEX__(value:&ClassClassRef) {
 CLASS_VALUE_METADATA___INDEX__.with(|slot|{slot.get_or_init(||Box::leak(Box::new(value.clone())));});
}
'''
