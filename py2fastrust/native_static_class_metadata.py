"""Share successful module class metadata without conflating retry generations."""


def once(model,owner):
    unit=model.unit
    if unit is None:return False
    if hasattr(unit,'original_unit'):unit=unit.original_unit(owner.node)
    return any(statement is owner.node for statement in unit.tree.body)


def layout(model,owner,member,initialize):
    from .native_value_classes import selected
    if(not selected(model,owner)or not once(model,owner)
            or member!='class_definition:ClassClassRef'
            or initialize!='class_definition:class_definition.clone()'):
        return member,initialize,''
    index=str(owner.index)
    name='class_value_metadata_'+index
    runtime=RUNTIME.replace('__INDEX__',index)
    return('class_definition:ClassValueMetadata_'+index,
           'class_definition:'+name+'(&class_definition)',runtime)


RUNTIME=r'''
#[derive(Clone)]
struct ClassValueMetadata___INDEX__(Option<ClassClassRef>);
impl std::ops::Deref for ClassValueMetadata___INDEX__ {
 type Target=ClassClassRef;
 fn deref(&self)->&ClassClassRef {
  if let Some(value)=&self.0 {return value;}
  CLASS_VALUE_METADATA___INDEX__.with(|slot|*slot.get().expect("retained class metadata"))
 }
}
impl ClassValueMetadata___INDEX__ {
 fn clone(&self)->ClassClassRef {Rc::clone(std::ops::Deref::deref(self))}
}
thread_local! {
 static CLASS_VALUE_METADATA___INDEX__:std::cell::OnceCell<&'static ClassClassRef>=std::cell::OnceCell::new();
}
fn class_value_metadata___INDEX__(value:&ClassClassRef)->ClassValueMetadata___INDEX__ {
 if value.module.borrow().class_module_status!=1 {return ClassValueMetadata___INDEX__(Some(value.clone()));}
 let pinned=CLASS_VALUE_METADATA___INDEX__.with(|slot|*slot.get_or_init(||Box::leak(Box::new(value.clone()))));
 if Rc::ptr_eq(pinned,value) {ClassValueMetadata___INDEX__(None)}
 else {ClassValueMetadata___INDEX__(Some(value.clone()))}
}
'''
