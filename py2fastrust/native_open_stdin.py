"""``open(0)``: a text file over standard input with universal newlines.

CPython's open(0) builds its own TextIOWrapper on file descriptor 0 with
``newline=None``, so "\\r\\n" and a lone "\\r" both read as "\\n" (sys.stdin on
POSIX uses ``newline="\\n"`` and translates nothing). The wrapper has its own
buffer; this adapter reads through the shared native input buffer, which is
exact only when no other standard-input reader exists. It is therefore
admitted for a single ``open(0)`` evaluated at most once (module level, outside
loops, functions and comprehensions) in a program without input() or sys.stdin.
Each raw line read up to "\\n" is split at lone "\\r" characters; the extra
lines wait in a queue for the next read.
"""
import ast

TAG = 'stdin_file'
METHODS = frozenset({'read', 'readline', 'readlines'})
_REPEATING = (ast.For, ast.AsyncFor, ast.While, ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef,
              ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


def _opens(tree):
    return [node for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'open']


def requires_frames(unit):
    return any(_descriptor_zero(node) for node in _opens(unit.tree))


def _descriptor_zero(node):
    return (len(node.args) == 1 and not node.keywords and isinstance(node.args[0], ast.Constant)
            and type(node.args[0].value) is int and node.args[0].value == 0)


def _reason(tree, call):
    if not _descriptor_zero(call):
        return 'open() of paths, other descriptors, or with mode/encoding arguments needs file-system and codec protocols; only open(0) is implemented'
    if len(_opens(tree)) != 1:
        return 'several open() calls would create separate buffered wrappers on standard input; a single open(0) is implemented'
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == 'input' or isinstance(node, ast.Attribute) and node.attr == 'stdin':
            return 'open(0) has its own buffer, so mixing it with input() or sys.stdin reads different data than CPython; programs with only open(0) are implemented'
    parents = {id(child): parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    child, current = call, parents.get(id(call))
    while current is not None:
        # A loop iterable and a comprehension's first iterable run once, outside the repetition.
        once = (isinstance(current, (ast.For, ast.AsyncFor)) and child is current.iter
                or isinstance(current, ast.comprehension) and child is current.iter
                and isinstance(parents.get(id(current)), (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp))
                and parents[id(current)].generators[0] is current)
        if once and isinstance(current, ast.comprehension):
            child, current = parents[id(current)], parents.get(id(parents[id(current)]))
            continue
        if not once and (isinstance(current, _REPEATING) or isinstance(current, ast.With)):
            return 'this open(0) may be evaluated more than once or used as a context manager; a single module-level evaluation is implemented'
        child, current = current, parents.get(id(current))
    return None


def analyze_call(model, node, cell):
    from .native_classes import ClassUnsupported
    reason = _reason(model.tree, node)
    if reason is not None:
        raise ClassUnsupported(node, reason, proof='standard-input file wrapper ownership')
    model.native_open_stdin_used = True
    return cell(TAG)


def analyze_method(model, plan, node, receiver, arguments, keywords):
    from .native_classes import Cell, ClassUnsupported, shape
    if shape(receiver) != TAG:
        return None
    name = node.func.attr
    if name not in METHODS:
        raise ClassUnsupported(node, f'this standard-input file method {name!r} is not implemented; read(), readline(), readlines() and iteration are',
                               proof='standard-input file method protocol')
    if arguments or keywords:
        raise ClassUnsupported(node, f'{name}() with a size or hint argument is not implemented for open(0); the argument-free form is',
                               proof='standard-input file size argument')
    if name == 'readlines':
        return model.cell(plan, node, 'list', (Cell('str'),))
    return model.cell(plan, node, 'str')


def emit_method(emitter, node, receiver, wanted):
    from .native_classes import Expression
    if receiver.kind != TAG:
        return None
    name = node.func.attr
    call = emitter.at('class_file0_' + name + '(&class_scope)', node)
    if name == 'readlines':
        item = emitter.fresh()
        converted = emitter.coerce(Expression('NativeText::from(' + item + ')', 'str'), wanted.element, node)
        return Expression('class_list((' + call + ').into_iter().map(|' + item + '|' + converted + ').collect::<Vec<_>>())', wanted)
    return Expression(emitter.coerce(Expression('NativeText::from(' + call + ')', 'str'), wanted, node), wanted)


RUNTIME = r'''
thread_local!{static CLASS_FILE0_PENDING:RefCell<std::collections::VecDeque<String>>=RefCell::new(std::collections::VecDeque::new());}
fn class_file0_split(raw:&str)->std::collections::VecDeque<String>{
    let mut lines=std::collections::VecDeque::new();let mut current=String::new();let mut chars=raw.chars().peekable();
    while let Some(c)=chars.next(){
        if c=='\r'{if chars.peek()==Some(&'\n'){chars.next();}current.push('\n');lines.push_back(std::mem::take(&mut current));}
        else if c=='\n'{current.push('\n');lines.push_back(std::mem::take(&mut current));}
        else{current.push(c);}
    }
    if !current.is_empty(){lines.push_back(current);}
    lines
}
fn class_file0_readline(scope:&ClassScope)->Result<String,String>{
    if let Some(line)=CLASS_FILE0_PENDING.with(|pending|pending.borrow_mut().pop_front()){return Ok(line);}
    let raw=class_read_text(scope,true,false)?;
    let mut lines=class_file0_split(&raw);
    let first=lines.pop_front().unwrap_or_default();
    CLASS_FILE0_PENDING.with(|pending|pending.borrow_mut().extend(lines));
    Ok(first)
}
fn class_file0_read(scope:&ClassScope)->Result<String,String>{
    let mut result:String=CLASS_FILE0_PENDING.with(|pending|pending.borrow_mut().drain(..).collect());
    let raw=class_read_text(scope,false,false)?;
    for line in class_file0_split(&raw){result.push_str(&line);}
    Ok(result)
}
fn class_file0_readlines(scope:&ClassScope)->Result<Vec<String>,String>{
    let mut lines=Vec::new();
    loop{let line=class_file0_readline(scope)?;if line.is_empty(){return Ok(lines);}lines.push(line);}
}
'''


def runtime(model):
    return RUNTIME if getattr(model, 'native_open_stdin_used', False) else ''
