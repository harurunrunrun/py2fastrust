"""Typed cursors for actual CP-compatible set-table allocation families."""


def accepts(model,kind):return model.mappings.cpython_sets.owns(kind)


def payload(emitter,kind):
    from .native_classes import shape
    from .native_class_mappings import canonical_type
    key=shape(kind.record.key)
    return 'NativeCPSetCursor<'+emitter.rust_type(key)+','+canonical_type(key)+'>'


def construct(code):return 'NativeCPSetCursor::new('+code+')'


def hint(emitter,node,kind,code):
    from .native_classes import ClassUnsupported
    if not accepts(emitter.model,kind):
        raise ClassUnsupported(node,'this set cursor has no registered CP-compatible table and remaining-length hint state',types=(('iterator source',kind),),proof='registered typed CP set cursor hint')
    value=emitter.fresh()
    checked=('{let '+value+'=('+code+').length_hint();if '+value+'<0{'
             'Err::<usize,String>("ValueError: __length_hint__() should return >= 0".to_owned())'
             '}else{usize::try_from('+value+').map_err(|_|"OverflowError: Python int too large to convert to C ssize_t".to_owned())}}')
    return emitter.at(checked,node)


def pull(emitter,node,kind,code,wanted):
    from .native_classes import Expression,shape
    item=emitter.fresh()
    converted=emitter.coerce(Expression(item,shape(kind.record.key)),wanted,node)
    return 'match '+emitter.at(code+'.next()',node)+'{Some('+item+')=>Some('+converted+'),None=>None}'
