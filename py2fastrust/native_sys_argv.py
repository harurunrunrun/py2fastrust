"""Lazy typed canonical sys.argv data, independent of the process entry ABI."""
import ast
from dataclasses import dataclass


@dataclass
class Arguments:
    module: object
    key: object
    value: object


def seed(linker, module, name):
    if not (module.native_adapter and module.name == 'sys' and name == 'argv'):
        return False
    model = linker.model
    record = getattr(model, 'sys_argv_data', None)
    if record is None:
        from .native_classes import Cell
        original = model.unit.main.tree
        value = model.cell(model.module, original, 'list', (Cell('str'),),
                           identity=('canonical_module_data', 'sys', 'argv'))
        record = model.sys_argv_data = Arguments(module,
            model.unit.global_name('sys', 'argv'), value)
    namespace = model.namespace
    namespace.incoming.setdefault(record.key, {})[('sys_argv_initial', module.number)] = record.value
    namespace.active.add(record.key)
    namespace.refresh(record.key, model.tree)
    return True


def matches(model, module, name):
    record = getattr(model, 'sys_argv_data', None)
    return record is not None and module.number == record.module.number and name == 'argv'


def layout(model):
    record = getattr(model, 'sys_argv_data', None)
    if record is None:
        return '', ''
    return ('class_sys_argv_pending:bool,',
            'class_sys_argv_pending:module==' + str(record.module.number) + ',')


def before_read(emitter, module, name, owner, node):
    if not matches(emitter.model, module, name):
        return ''
    return emitter.at('native_sys_argv_initialize(&' + owner + ')', node) + ';'


def store(emitter, module, name, owner, value, wanted, field, node, mark):
    if not matches(emitter.model, module, name):
        return None
    converted = emitter.fresh()
    removed = emitter.fresh()
    namespace = emitter.fresh()
    return ('{let ' + converted + '=' + emitter.coerce(value, wanted, node) + ';'
            + 'let ' + removed + '={let mut ' + namespace + '=' + owner + '.borrow_mut();'
            + 'let previous=' + namespace + '.value_' + str(field) + '.replace(' + converted + ');'
            + namespace + '.class_sys_argv_pending=false;previous};drop(' + removed + ');'
            + mark + '}')


def runtime(model, emitter):
    record = getattr(model, 'sys_argv_data', None)
    if record is None:
        return ''
    from .native_classes import Expression, shape
    initial = shape(record.value)
    element = initial.element
    wanted = dict(model.namespace.fields())[record.key]
    field = model.namespace.index(record.key)
    converted = emitter.coerce(Expression('text', 'str'), element, model.tree)
    stored = emitter.coerce(Expression('class_list(values)', initial), wanted, model.tree)
    provider = r'''
fn native_program_arguments<I>(arguments:I)->Result<Vec<NativeText>,String>
where I:IntoIterator<Item=std::ffi::OsString>{
    let mut values=Vec::new();
    for (index,argument) in arguments.into_iter().enumerate(){
        let value=match argument.into_string(){
            Ok(value)=>value,
            Err(argument)=>{
                let raw=argument.as_os_str().as_encoded_bytes();
                let bytes=raw.iter().map(|value|format!("{:02x}",value)).collect::<String>();
                return Err(format!("RuntimeError: sys.argv argument {} contains non-Unicode OS bytes (hex {}); surrogateescape string representation is not implemented",index,bytes));
            }
        };
        values.try_reserve(1).map_err(|_|"MemoryError".to_owned())?;
        values.push(NativeText::from(value));
    }
    Ok(values)
}
'''
    return provider + ('fn native_sys_argv_initialize(globals:&ClassModuleRef)->Result<(),String>{'
        + 'if !globals.borrow().class_sys_argv_pending{return Ok(());}'
        + 'let arguments=native_program_arguments(std::env::args_os())?;'
        + 'let mut values=Vec::<' + emitter.rust_type(element) + '>::new();'
        + 'values.try_reserve(arguments.len()).map_err(|_|"MemoryError".to_owned())?;'
        + 'for text in arguments{values.push(' + converted + ');}'
        + 'let value=' + stored + ';let mut namespace=globals.borrow_mut();'
        + 'namespace.value_' + str(field) + '=Some(value);'
        + 'namespace.class_sys_argv_pending=false;Ok(())}')


def point(linker, module, name, plan, node):
    """A completed current store or the initial main-frame producer, without reentry."""
    model = linker.model
    if not matches(model, module, name):
        return None
    from .native_classes import shape
    if model.namespace.globals_observed or getattr(model, 'gc_classes', ()):
        return None
    if any('__del__' in owner.methods for owner in model.classes.values()):
        return None
    if any(isinstance(value, (ast.Yield, ast.YieldFrom, ast.GeneratorExp, ast.AsyncFunctionDef))
           for value in model.iter_nodes()):
        return None
    if any(getattr(shape(cell), '_native_namespace_view', False) for cell in model.records.values()):
        return None
    if any(model.display_name(row.name) == '__builtins__' for row in model.iter_bindings()):
        return None
    hooks = {'__import__', '__getattr__', '__class__', '__dict__', '__setattr__'}
    if any((getattr(key, 'module_name', None) == module.name and model.display_name(key) in hooks)
           or model.display_name(key) == '__import__' for key in model.namespace.incoming):
        return None
    from .native_builtin_namespace_points import _prefix, _slot
    parents = model.unit.parents
    statement = node
    while not isinstance(statement, ast.stmt):
        statement = parents.get(id(statement))
        if statement is None:
            return None
    parent = parents.get(id(statement))
    if parent is None or not _prefix(model, plan, node, statement, module):
        return None
    siblings = next((value for _, value in ast.iter_fields(parent)
                     if isinstance(value, list) and statement in value
                     and all(isinstance(item, ast.stmt) for item in value)), None)
    if siblings is None:
        return None
    for previous in reversed(siblings[:siblings.index(statement)]):
        if (isinstance(previous, ast.Assign) and len(previous.targets) == 1
                and _slot(model, plan, previous.targets[0], module, name)):
            return model.records.get((plan.index, id(previous.value)))
        if isinstance(previous, ast.Assign) and any(
                _slot(model, plan, target, module, name) for target in previous.targets):
            return None
        if not _inert(model, plan, previous):
            return None
    # An imported source module may start after arbitrary caller effects. Only
    # the actual original entry module starts with the initial argv binding.
    if plan is model.module and parent is model.unit.main.tree:
        return model.sys_argv_data.value
    return None


def _inert(model, plan, statement):
    from .native_builtin_namespace_points import _statement, _kind, _pure
    if _statement(model, plan, statement):
        return True
    if isinstance(statement, (ast.Import, ast.ImportFrom)):
        for binding in model.unit.import_bindings(statement):
            module = model.module_linker.modules[binding.module]
            if module.initializer is not None:
                return False
            if model.unit.global_name(module.name, '__getattr__') in model.namespace.incoming:
                return False
            for child in binding.children:
                if model.module_linker.modules[child].initializer is not None:
                    return False
        return True
    if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
        return False
    call = statement.value
    if any(isinstance(value, ast.Starred) for value in call.args):
        return False
    from .native_physical_list_builtins import static_builtin
    # Canonical stream replacement and write/flush overrides are currently
    # rejected by module/stdio admission. Source sinks need a new effect proof.
    if static_builtin(model, plan, call.func, 'print'):
        if any(keyword.arg not in {'sep', 'end', 'flush'} for keyword in call.keywords):
            return False
        from .native_integer_digit_limits import _pure_builtin_display
        if not all(_closed_expression(model, plan, value) and _pure_builtin_display(_kind(model, plan, value))
                   for value in call.args):
            return False
        for keyword in call.keywords:
            if not _pure(model, plan, keyword.value):
                return False
            kind = _kind(model, plan, keyword.value)
            if keyword.arg in {'sep', 'end'} and kind not in {'str', 'none'}:
                return False
            if keyword.arg == 'flush' and kind not in {'str', 'bytes', 'int', 'bool', 'int_bool', 'float', 'none'}:
                return False
        return True
    if not (isinstance(call.func, ast.Attribute) and call.func.attr == 'append'
            and len(call.args) == 1 and not call.keywords):
        return False
    from .native_types import alternatives, list_type
    receiver = _kind(model, plan, call.func.value)
    return (all(list_type(kind) for kind in alternatives(receiver))
            and _pure(model, plan, call.func.value) and _pure(model, plan, call.args[0]))


def _closed_expression(model, plan, node):
    from .native_builtin_namespace_points import _pure
    if _pure(model, plan, node):
        return True
    if isinstance(node, ast.Compare) and all(isinstance(op, (ast.Is, ast.IsNot)) for op in node.ops):
        return all(_pure(model, plan, child) for child in (node.left, *node.comparators))
    return False
