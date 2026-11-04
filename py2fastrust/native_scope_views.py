"""Retain an owned execution context only when a call changes its module.

This late pass operates on compiler-owned synchronous Rust bindings. It runs
after the finite-depth certificate, which excludes observable reference counts,
reentrant finalizers, suspended calls and unknown runtime protocols. The module
argument is evaluated and captured normally before comparing its actual Rc.
"""
from .native_scope_borrows import body_index, shared_scope, _scope_uses_borrowable
from .rust_pruning import _lex, _parse, _Unsupported


WITH_MODULE = ('fn with_module(&self,globals:ClassModuleRef)->Self{Self{'
               'control:self.control.clone(),io:self.io.clone(),globals,'
               'modules:self.modules.clone()}}')

RUNTIME = '''
enum ClassScopeView<'a>{Borrowed(&'a ClassScope),Owned(ClassScope)}
impl std::ops::Deref for ClassScopeView<'_>{
 type Target=ClassScope;
 fn deref(&self)->&ClassScope{match self{Self::Borrowed(value)=>value,Self::Owned(value)=>value}}
}
impl ClassScopeView<'_>{
 fn clone(&self)->ClassScope{std::ops::Deref::deref(self).clone()}
}
impl ClassScope{
 fn with_module_view(&self,globals:ClassModuleRef)->ClassScopeView<'_>{
  if Rc::ptr_eq(&self.globals,&globals){ClassScopeView::Borrowed(self)}
  else{ClassScopeView::Owned(self.with_module(globals))}
 }
}
'''


def _concrete_scope_calls(tokens, pairs, items, positions):
    """Only a concrete reference formal permits normal Rust Deref coercion.

    A generic `f(&class_scope)` or qualified trait call could infer the view
    itself. Do not change that Rust ABI, or a shadowed/address-taken callee.
    """
    result = set()
    for item in items:
        if item.kind != 'fn':
            continue
        first = positions[item.start]
        declaration = next(i for i in range(first, len(tokens))
                           if tokens[i].text == 'fn')
        cursor = declaration + 2
        if tokens[cursor].text == '<':
            depth = 0
            generic_start = cursor
            while cursor < len(tokens):
                text = tokens[cursor].text
                if set(text) <= {'<', '>'}:
                    depth += text.count('<') - text.count('>')
                cursor += 1
                if not depth:
                    break
            if any(token.text == 'ClassScope' for token in tokens[generic_start:cursor]):
                # `fn f<ClassScope: Clone>(x: &ClassScope)` names a generic
                # parameter, not the nominal runtime execution context.
                continue
        if tokens[cursor].text != '(':
            continue
        end = pairs[cursor]
        parameter = tokens[cursor+1:end]
        if len(parameter) >= 4 and [token.text for token in parameter[1:4]] == [':', '&', 'ClassScope']:
            if len(parameter) == 4 or parameter[4].text == ',':
                result.add(item.name)
    # Nested functions and inherent/trait members have their own lexical name
    # resolution. A top-level spelling alone cannot disambiguate those calls.
    declarations = {}
    for i, token in enumerate(tokens[:-1]):
        if token.text == 'fn':
            name = tokens[i+1].text
            declarations[name] = declarations.get(name, 0) + 1
    result = {name for name in result if declarations.get(name) == 1}
    escaped = {token.text for i, token in enumerate(tokens[:-1])
               if token.text in result and (not i or tokens[i-1].text != 'fn')
               and tokens[i+1].text != '('}
    return result - escaped


def _view_uses_borrowable(tokens, start, end, callees):
    if not _scope_uses_borrowable(tokens, start, end):
        return False
    for i in range(start, end):
        if tokens[i].text != 'class_scope' or not i or tokens[i-1].text != '&':
            continue
        if (i < 3 or tokens[i-2].text != '(' or tokens[i-3].text not in callees
                or i >= 4 and tokens[i-4].text in {'.', ':', '::'}
                or i+1 >= end or tokens[i+1].text not in {',', ')'}):
            return False
    return True


def apply(source, model):
    info = {'eligible': False, 'sites': 0, 'functions': []}
    model.scope_views = info
    if not getattr(model, 'finite_depth_calls', {}).get('eligible'):
        info['reason'] = 'the finite synchronous source/runtime certificate is unavailable'
        return source
    try:
        tokens, comments, pairs = _lex(source)
        items = _parse(source, tokens, comments, pairs)
        if not shared_scope(tokens, pairs, items):
            info['reason'] = 'the context has an unproved shared-field or destructor layout'
            return source
        if any(token.text == 'ClassScopeView' for token in tokens):
            info['reason'] = 'an execution-context view is already present'
            return source
        methods = [child for item in items if item.kind == 'impl' and not item.trait
                   and item.owner == 'ClassScope' for child in item.children
                   if child.kind == 'fn' and child.name == 'with_module']
        expected = [token.text for token in _lex(WITH_MODULE)[0]]
        if len(methods) != 1 or [token.text for token in tokens
                if methods[0].start <= token.start < methods[0].end] != expected:
            info['reason'] = 'the original module-context constructor is not canonical'
            return source
        positions = {token.start: i for i, token in enumerate(tokens)}
        callees = _concrete_scope_calls(tokens, pairs, items, positions)
        edits = []
        for item in items:
            if item.kind != 'fn':
                continue
            first = positions[item.start]
            declaration = next(i for i in range(first, len(tokens))
                               if tokens[i].text == 'fn')
            if any(token.text in {'async', 'const', 'unsafe', 'extern'}
                   for token in tokens[first:declaration]):
                continue
            opening = declaration + 2
            if tokens[opening].text != '(':
                continue
            closing = pairs[opening]
            parameter = [token.text for token in tokens[opening+1:closing]]
            if not (parameter[:3] == ['class_scope', ':', 'ClassScope']
                    or parameter[:4] == ['class_scope', ':', '&', 'ClassScope']):
                continue
            body = body_index(tokens, pairs, opening, item.end)
            if body is None or any(token.text in {'ClassFuture', 'ClassTask', 'ClassCall'}
                                   for token in tokens[closing+1:body]):
                continue
            end = pairs[body]
            if not _view_uses_borrowable(tokens, body+1, end, callees):
                continue
            count = 0
            for i in range(body+1, end-6):
                if [token.text for token in tokens[i:i+7]] != [
                        'let', 'class_scope', '=', 'class_scope', '.', 'with_module', '(']:
                    continue
                stop = pairs[i+6]
                # A complete private let-binding, rather than a borrowed value
                # embedded in an arbitrary expression or retained aggregate.
                if tokens[stop+1].text != ';':
                    continue
                edits.append((tokens[i+5].start, tokens[i+5].end, 'with_module_view'))
                count += 1
            if count:
                info['functions'].append(item.name)
        if not edits:
            info['reason'] = 'no synchronous borrow-only private module binding was proved'
            return source
        for start, end, replacement in sorted(edits, reverse=True):
            source = source[:start] + replacement + source[end:]
        info.update(eligible=True, sites=len(edits))
        return source + RUNTIME
    except (_Unsupported, StopIteration, KeyError, IndexError) as error:
        info['reason'] = str(error) or type(error).__name__
        return source
