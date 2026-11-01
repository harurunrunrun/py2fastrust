"""Delete concrete instance slots and registered indexed deque storage.

The outer Option represents attribute presence. An inner Option may be the
actual Python value None and does not change the deletion presence test.
"""
import ast


def analyze(model,plan,target,environment):
    """Consume supported field or recursive delete targets, preserving order."""
    if isinstance(target,(ast.Tuple,ast.List)):
        from .native_annotations import metadata_target
        for child in target.elts:
            metadata_target(model,plan,child,environment)
            if not analyze(model,plan,child,environment):
                if not model.lexical.delete(plan,child,environment):model.namespace.delete(plan,child,environment)
        return True
    if isinstance(target,ast.Subscript):return model.deques.indexes.analyze_delete(plan,target,environment)
    if not isinstance(target,ast.Attribute):return False
    from .native_classes import ClassUnsupported,shape
    receiver=model.expression(plan,target.value,environment).root()
    if receiver.tag is None and not model.final:return True
    if receiver.tag!='object':
        raise ClassUnsupported(target,"deleting this attribute needs an object attribute-deletion protocol; this typed path only owns concrete source-instance field slots",types=(("receiver",shape(receiver)),),proof="resolved instance attribute-deletion storage")
    owner=model.classes[receiver.args[0]]
    name=model.resolved_name(plan,target)
    if name.startswith('__')and name.endswith('__'):
        raise ClassUnsupported(target,"deleting this special attribute requires Python's instance-dictionary or special descriptor deletion protocol, which is not implemented for typed field slots",operation='special attribute deletion '+repr(target.attr),proof="instance dictionary and descriptor deletion semantics")
    if name in owner.methods:
        raise ClassUnsupported(target,"deleting a method-valued attribute requires instance-dictionary and descriptor lookup precedence; this typed path does not store per-instance method overrides",proof="method descriptor deletion lookup")
    # A never-written field remains an absent Option, so deleting a known
    # missing name raises at runtime rather than silently creating a value.
    model.field(owner,name,target)
    return True


def lower(emitter,target):
    """Capture each receiver once and release its borrow before dropping data."""
    if isinstance(target,(ast.Tuple,ast.List)):
        from .native_class_globals import delete
        pieces=[]
        for child in target.elts:
            code=lower(emitter,child)
            if code is None:
                code=(emitter.model.lexical.emit_delete(emitter,child)
                      if emitter.model.lexical.field_for(child)is not None else delete(emitter,child))
            pieces.append(code)
        return ''.join(pieces)
    if isinstance(target,ast.Subscript):return emitter.model.deques.indexes.emit_delete(emitter,target)
    if not isinstance(target,ast.Attribute):return None
    from .native import _string
    setup,reference=emitter.reference(target)
    _,receiver,owner,index,_=reference
    message=_string("AttributeError: '"+owner.node.name+"' object has no attribute '"+emitter.model.resolved_name(emitter.plan,target)+"'")
    removed=emitter.fresh()
    code=('{let '+removed+'={'+receiver.code+'.borrow_mut().field_'+str(index)+'.take()};'
          'if '+removed+'.is_some(){Ok(())}else{Err('+message+'.to_owned())}}')
    return setup+emitter.at(code,target)+';'
