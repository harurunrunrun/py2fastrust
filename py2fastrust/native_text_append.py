"""``name += text`` on str variables appends in place when the variable holds the only reference.

Python evaluates the target, then the right operand, then concatenates and
stores the result. The frame emitter keeps that order. After the right operand
is evaluated no Python code runs before the store, so the variable's own
reference is released first; the loaded text is then usually unique and grows
in its own buffer instead of being copied on every iteration. On MemoryError
the variable keeps its previous text, as the failed concatenation leaves it.
"""
import ast

RUNTIME = r'''
fn class_text_append(left:&mut NativeText,right:&str)->Result<(),String> {
    let mut text=std::mem::take(left).into_string();
    if text.try_reserve(right.len()).is_err(){*left=NativeText::from(text);return Err("MemoryError: string is too large".to_string());}
    text.push_str(right);*left=NativeText::from(text);Ok(())
}
'''


def emit(emitter, node, setup, reference, old_kind):
    from .native_classes import Expression
    if not (isinstance(node.target, ast.Name) and isinstance(node.op, ast.Add) and old_kind == 'str'):
        return None
    if emitter.kind(node.target) != 'str' or emitter.kind(node.value) != 'str':
        return None
    before, old = emitter.capture(emitter.load_reference(reference, node.target, old_kind))
    more, right = emitter.capture(emitter.expression(node.value))
    if old.kind != 'str' or right.kind != 'str':
        return None
    text, outcome = emitter.fresh(), emitter.fresh()
    emitter.model.text_append_required = True
    release = emitter.store_reference(reference, Expression('NativeText::default()', 'str'), node.target)
    commit = emitter.store_reference(reference, Expression(text, 'str'), node.target)
    return ('{' + setup + before + more + 'let mut ' + text + '=' + old.code + ';' + release
            + 'let ' + outcome + '=class_text_append(&mut ' + text + ',&' + right.code + ');' + commit
            + emitter.at(outcome, node) + ';}')


def runtime(model):
    return RUNTIME if getattr(model, 'text_append_required', False) else ''
