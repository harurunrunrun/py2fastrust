"""``del list[index]`` and ``del list[slice]`` following Objects/listobject.c (3.14).

The receiver is evaluated first, then the index or slice bounds. An item
index is normalized once against the current length and reports
``IndexError: list assignment index out of range`` outside it. A slice uses
the same index adjustment as slice reads; a step of 1 removes one contiguous
run, other steps remove every selected position, and a zero step raises
``ValueError`` before any element is removed.
"""
import ast

INTEGRAL = frozenset({'int', 'bool', 'int_bool'})


def _list_owner(owner):
    from .native_classes import domain, shape
    return domain(shape(owner)) == 'list'


def requires_frames(unit, analysis):
    from .native_types import ListType, alternatives
    for node in ast.walk(unit.tree):
        if not isinstance(node, ast.Delete):
            continue
        for target in node.targets:
            for child in ast.walk(target):
                if isinstance(child, ast.Subscript) and any(
                        isinstance(part, ListType)
                        for facts in analysis.scopes.values()
                        for part in alternatives(facts.expressions.get(unit.ordinal(child.value)))):
                    return True
    return False


def analyze(model, plan, target, environment):
    from .native_classes import ClassUnsupported, shape
    from .native_types import alternatives
    if not isinstance(target, ast.Subscript):
        return False
    owner = model.expression(plan, target.value, environment)
    if shape(owner) is None and not model.final:
        return False
    if not _list_owner(owner):
        return False
    parts = (target.slice.lower, target.slice.upper, target.slice.step) if isinstance(target.slice, ast.Slice) else (target.slice,)
    for part in parts:
        if part is None:
            continue
        value = model.expression(plan, part, environment)
        kinds = alternatives(shape(value))
        allowed = INTEGRAL | {'none'} if isinstance(target.slice, ast.Slice) else INTEGRAL
        if any(kind is not None and kind not in allowed for kind in kinds):
            raise ClassUnsupported(part, 'this list deletion index needs its __index__ conversion or TypeError protocol; builtin integer indices and slice bounds are implemented',
                                   types=(('index', shape(value)),), proof='list deletion index conversion')
    from .native_union_sequences import branches
    from .native_list_positions import invalidate
    for choice in branches(owner):
        if choice.tag == 'list':
            invalidate(model, choice)
    sites = getattr(model, 'list_deletion_sites', None)
    if sites is None:
        sites = model.list_deletion_sites = set()
    sites.add((plan.index, id(target)))
    return True


def emit(emitter, target):
    from .native_classes import Expression
    if (emitter.plan.index, id(target)) not in getattr(emitter.model, 'list_deletion_sites', ()):
        return None
    before, owner = emitter.capture(emitter.expression(target.value))
    emitter.model.native_list_deletion_required = True
    if isinstance(target.slice, ast.Slice):
        from .native_frame_slices import convert_bounds
        bounds = []
        for part in (target.slice.lower, target.slice.upper, target.slice.step):
            if part is None:
                bounds.append(None)
                continue
            setup, value = emitter.capture(emitter.expression(part))
            before += setup
            bounds.append(value)
        setup, names = convert_bounds(emitter, target, bounds)
        emitter.model.native_frame_slices_required = True
        call = 'class_list_delete_slice(&' + owner.code + ',' + ','.join(names) + ')'
        return '{' + before + setup + emitter.at(call, target) + ';}'
    setup, index = emitter.capture(emitter.expression(target.slice))
    number = emitter.number(index)
    wide = '(' + number + ').to_i128()' if emitter.model.integer == 'bigint' else 'Some((' + number + ') as i128)'
    call = 'class_list_delete_item(&' + owner.code + ',' + wide + ')'
    return '{' + before + setup + emitter.at(call, target) + ';}'


RUNTIME = r'''
fn class_list_delete_item<T>(owner:&Rc<RefCell<Vec<T>>>,index:Option<i128>)->Result<(),String>{
 let index=index.filter(|index|isize::try_from(*index).is_ok()).ok_or_else(||"IndexError: cannot fit 'int' into an index-sized integer".to_owned())?;
 let removed={
  let mut target=owner.borrow_mut();let length=target.len() as i128;
  let position=if index<0{index+length}else{index};
  if position<0||position>=length{return Err("IndexError: list assignment index out of range".to_owned());}
  target.remove(position as usize)
 };
 drop(removed);Ok(())
}
fn class_list_delete_slice<T>(owner:&Rc<RefCell<Vec<T>>>,start:Option<i128>,stop:Option<i128>,step:Option<i128>)->Result<(),String>{
 let removed:Vec<T>={
  let mut target=owner.borrow_mut();
  let indices=native_slice_indices(target.len(),start,stop,step)?;
  if indices.len()==0{Vec::new()}
  else if step.unwrap_or(1)==1{
   let begin=usize::try_from(indices.cursor).expect("bounded forward slice");
   target.drain(begin..begin+indices.len()).collect()
  }else{
   let mut keep=vec![true;target.len()];
   for index in indices{keep[index]=false;}
   let mut position=0;let mut removed=Vec::new();
   let mut kept=Vec::with_capacity(target.len());
   for value in target.drain(..){if keep[position]{kept.push(value);}else{removed.push(value);}position+=1;}
   *target=kept;removed
  }
 };
 drop(removed);Ok(())
}
'''


def runtime(model):
    return RUNTIME if getattr(model, 'native_list_deletion_required', False) else ''
