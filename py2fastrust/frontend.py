"""One official Python frontend shared by every direct Rust emitter.

This representation contains source structure and lexical facts, never VM
instructions. Parsed ASTs are owned read-only views; metadata and collections
are frozen. Contextual validation compiles the existing AST without executing
it. Only imports present in source (or explicitly included) are resolved.
"""
from __future__ import annotations

import ast
import __future__
import io
import symtable
import tokenize
from dataclasses import dataclass, replace
from importlib.resources import files
from pathlib import Path
from types import MappingProxyType

from .diagnostics import CompilationError, Diagnostic
from .source_locations import SourceLocation
from .module_catalog import BUILTIN_MODULES, VENDORED_MODULES


_FUTURE_MASK = sum(getattr(__future__, name).compiler_flag for name in __future__.all_feature_names) & ~0x10


def private_name(name, owner):
    """Python lexical identifier/attribute mangling; call keywords stay literal."""
    if owner and name.startswith("__") and not name.endswith("__") and "." not in name:
        prefix=owner.lstrip("_")
        if prefix:return "_"+prefix+name
    return name


class _FrozenList(list):
    def _immutable(self, *args, **kwargs):
        raise TypeError("parsed source is immutable")
    __setitem__ = __delitem__ = __iadd__ = __imul__ = _immutable
    append = clear = extend = insert = pop = remove = reverse = sort = _immutable


_FROZEN_AST_TYPES = {}


def _freeze_tree(tree):
    """Keep ast's isinstance/list interfaces without allowing emitter mutation.

    Official operator/context singleton tokens have no semantic fields and
    retain their exact official types for operator dispatch in existing emitters.
    """
    def immutable(self, *args):
        raise TypeError("parsed source is immutable")
    def attributes(self, name):
        value = object.__getattribute__(self, name)
        return MappingProxyType(value) if name == "__dict__" else value
    def freeze(node):
        if isinstance(node, (ast.operator, ast.unaryop, ast.boolop, ast.cmpop, ast.expr_context)):
            return node
        for name, value in ast.iter_fields(node):
            if isinstance(value, ast.AST):
                object.__setattr__(node, name, freeze(value))
            elif isinstance(value, list):
                object.__setattr__(node, name, _FrozenList(freeze(item) if isinstance(item, ast.AST) else item for item in value))
        original = type(node)
        if original not in _FROZEN_AST_TYPES:
            _FROZEN_AST_TYPES[original] = type(original.__name__, (original,), {
                "__slots__": (), "__module__": __name__, "__setattr__": immutable,
                "__delattr__": immutable, "__getattribute__": attributes,
            })
        object.__setattr__(node, "__class__", _FROZEN_AST_TYPES[original])
        return node
    return freeze(tree)


@dataclass(frozen=True)
class Symbol:
    name: str
    flags: frozenset[str]

    def has(self, flag):
        return flag in self.flags


@dataclass(frozen=True)
class Scope:
    ordinal: int
    parent: int | None
    name: str
    kind: str
    line: int
    symbols: tuple[Symbol, ...]
    children: tuple[int, ...]


@dataclass(frozen=True)
class Binding:
    name: str
    role: str
    scope: int
    owner: int
    node: int


@dataclass(frozen=True)
class SourceNode:
    ordinal: int
    scope: int
    kind: str
    line: int
    column: int
    end_line: int
    end_column: int
    located: bool


@dataclass(frozen=True)
class ResolvedImport:
    node: int
    module: str
    names: tuple[str, ...]
    level: int
    origin: str
    filename: str | None
    children: tuple[str, ...] = ()


@dataclass(frozen=True)
class Module:
    name: str
    origin: str
    filename: str | None
    package: bool
    # Resolver-only search paths never enter emitted source or source maps.
    search_paths: tuple[Path, ...] = ()


@dataclass(frozen=True)
class SourceUnit:
    source: str
    filename: str
    name: str
    package: bool
    tree: ast.Module
    table: symtable.SymbolTable
    future_flags: int
    scopes: tuple[Scope, ...]
    nodes: tuple[SourceNode, ...]
    bindings: tuple[Binding, ...]
    imports: tuple[ResolvedImport, ...]
    native_imports: frozenset[str]
    node_ordinals: object
    definition_scopes: object
    resolved_names: object
    function_signatures: object

    def ordinal(self, node):
        return self.node_ordinals[id(node)]

    def scope_for(self, node):
        return self.scopes[self.definition_scopes[id(node)]]

    def name_for(self, node):
        return self.resolved_names[id(node)]

    def signature_for(self, node):
        return self.function_signatures[id(node)]

    def check_identity(self, source, filename):
        if self.source != source or self.filename != filename:
            raise ValueError("source unit does not match the supplied source and filename")


@dataclass(frozen=True)
class Program:
    main: SourceUnit
    units: tuple[SourceUnit, ...]
    modules: tuple[Module, ...]
    source_map: tuple[SourceLocation, ...]

    @property
    def native_imports(self):
        return self.main.native_imports

    def module(self, name):
        return next((item for item in self.modules if item.name == name), None)


def _scope_metadata(table):
    scopes = []
    tables = []
    def visit(current, parent):
        ordinal = len(scopes)
        scopes.append(None)
        tables.append(current)
        children = tuple(visit(child, ordinal) for child in current.get_children())
        symbols = []
        for symbol in current.get_symbols():
            flags = frozenset(name[3:] for name in dir(symbol)
                              if name.startswith("is_") and callable(getattr(symbol, name)) and getattr(symbol, name)())
            symbols.append(Symbol(symbol.get_name(), flags))
        kind = current.get_type()
        scopes[ordinal] = Scope(ordinal, parent, current.get_name(), getattr(kind, "value", str(kind)),
                                current.get_lineno(), tuple(symbols), children)
        return ordinal
    visit(table, None)
    return tuple(scopes), tuple(tables)


def _source_metadata(tree, scopes, *, future_annotations=False):
    # CPython 3.14 inlines list/set/dict comprehensions in its physical symbol
    # tables. Keep the official IDs, and append logical binding scopes instead
    # of pretending that an iteration target writes the enclosing namespace.
    scopes=list(scopes)
    official_count=len(scopes)
    physical_parents=tuple(scope.parent for scope in scopes)
    nodes, bindings, ordinals, definitions, names = [], [], {}, {}, {}
    annotation_syntax=set()
    pending_bindings=[]
    matched = {0}
    symbols = [{value.name: value for value in scope.symbols} for scope in scopes]
    inline_targets={}
    generator_scopes=set()
    declarations={}
    def physical_scope(scope):
        while scope>=official_count:scope=scopes[scope].parent
        return scope
    def enclosing_owner(scope,name,class_cell=False):
        while scope is not None:
            current=scopes[scope]
            symbol=symbols[scope].get(name)
            if current.kind=="class":
                if name in {"__class__","__classdict__"}:
                    # Bare inline class-body reads are global. Only an
                    # official free-variable closure captures the class cell.
                    return scope if class_cell else 0
            elif current.kind=="comprehension":
                if symbol and symbol.has("local"):return scope
            elif scope==0:return 0
            elif symbol:
                if symbol.has("global"):return 0
                if name in {"__class__","__classdict__"}and (symbol.has("free")or symbol.has("nonlocal")):
                    class_cell=True
                if (symbol.has("local")or symbol.has("parameter"))and not symbol.has("free_class"):
                    # The physical table may report a comp-only name as a
                    # local even though another comprehension sees it global.
                    if name not in inline_targets.get(scope,())or name in declarations.get(scope,()):return scope
            scope=current.parent
        return 0
    def scope_owner(scope, name):
        symbol = symbols[scope].get(name)
        if scopes[scope].kind=="comprehension":
            if symbol and symbol.has("local"):return scope
            return enclosing_owner(scopes[scope].parent,name)
        if symbol and symbol.has("global"):
            return 0
        if symbol and (symbol.has("free") or symbol.has("nonlocal")):
            return enclosing_owner(scopes[scope].parent,name,class_cell=name in {"__class__","__classdict__"})
        if name in inline_targets.get(scope,())and name not in declarations.get(scope,()):
            return enclosing_owner(scopes[scope].parent,name)
        return scope
    private_owner = [None]
    def bind(name, role, scope, ordinal, namespace=None):
        name = private_name(name, private_owner[0])
        pending_bindings.append((name,role,scope,ordinal,namespace))
    def child_scope(node, parent, name, kind):
        candidates = [scope.ordinal for scope in scopes[:official_count] if scope.ordinal not in matched
                      and scope.name == name and scope.kind == kind
                      and scope.line == getattr(node, "lineno", 1)]
        # Hidden annotation/type-parameter scopes can sit between the lexical
        # definition and its function body in the official table.
        def descendant(index):
            while index is not None:
                if index == physical_scope(parent):return True
                index = physical_parents[index]
            return False
        candidates = [index for index in candidates if descendant(index)]
        if not candidates:
            return parent
        def distance(index):
            index=physical_parents[index];length=0
            while index is not None and index!=physical_scope(parent):
                index=physical_parents[index];length+=1
            return length
        candidates.sort(key=lambda index:(distance(index),index))
        result = candidates[0]
        matched.add(result)
        definitions[id(node)] = result
        if parent>=official_count:
            scopes[result]=replace(scopes[result],parent=parent)
        return result
    def inline_scope(node,parent):
        targets={private_name(value.id,private_owner[0]):None
                 for generator in node.generators for value in ast.walk(generator.target)
                 if isinstance(value,ast.Name)}
        kind=type(node).__name__.lower()
        index=len(scopes)
        target_symbols=tuple(Symbol(name,frozenset({"local","assigned","comp_iter"}))for name in targets)
        scopes.append(Scope(index,parent,kind,"comprehension",node.lineno,target_symbols,()))
        symbols.append({symbol.name:symbol for symbol in target_symbols})
        inline_targets.setdefault(physical_scope(parent),set()).update(targets)
        definitions[id(node)]=index
        return index
    def walrus_scope(scope):
        while scopes[scope].kind=="comprehension"or scope in generator_scopes:
            scope=scopes[scope].parent
        return scope
    def visit(node, scope=0, defaults_scope=None, first_iter_scope=None, annotation_scope=None, namespace=None, skip_defaults=False, skip_iter=False, syntax_only=False):
        ordinal = len(nodes)
        ordinals[id(node)] = ordinal
        line, column = getattr(node, "lineno", 1), getattr(node, "col_offset", 0) + 1
        nodes.append(SourceNode(ordinal, scope, type(node).__name__, line, column,
                                getattr(node, "end_lineno", line) or line,
                                (getattr(node, "end_col_offset", column - 1) or 0) + 1, hasattr(node,"lineno")))
        if isinstance(node, ast.keyword):
            # CPython does not mangle keyword names at the call site.
            names[id(node)] = node.arg
        elif isinstance(node,(ast.Name,ast.Attribute,ast.arg)):
            raw = node.id if isinstance(node,ast.Name) else node.attr if isinstance(node,ast.Attribute) else node.arg
            names[id(node)] = private_name(raw,private_owner[0])
        elif isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
            names[id(node)] = private_name(node.name,private_owner[0])
        if syntax_only:
            # Stringized/local annotations retain their original AST and source
            # locations, but create no executable bindings, comprehensions or
            # callable frames in the official symbol table.
            annotation_syntax.add(id(node))
            for child in ast.iter_child_nodes(node):visit(child,scope,syntax_only=True)
            return
        if isinstance(node, ast.Name):
            bind(node.id, "load" if isinstance(node.ctx, ast.Load) else "delete" if isinstance(node.ctx, ast.Del) else "store", scope, ordinal,namespace)
        elif isinstance(node, ast.arg):
            bind(node.arg, "parameter", scope, ordinal)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bind(node.name, "definition", scope, ordinal)
        elif isinstance(node, ast.alias):
            bind(node.asname or node.name.split(".")[0], "import", scope, ordinal)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bind(node.name, "store", scope, ordinal)
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
            bind(node.name, "store", scope, ordinal)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            name = "lambda" if isinstance(node, ast.Lambda) else node.name
            definition_scope = child_scope(node, scope, node.name, "type parameters") if getattr(node,"type_params",()) else scope
            annotations_scope = child_scope(node, definition_scope, "__annotate__", "annotation")
            for decorator in getattr(node, "decorator_list", ()):
                visit(decorator, scope)
            # The physical table lists default-expression lambdas before the
            # callable itself, even when all lambdas share one source line.
            for default in (*node.args.defaults,*node.args.kw_defaults):
                if default is not None:visit(default,scope)
            body_scope = child_scope(node, definition_scope, name, "function")
            visit(node.args, body_scope, scope, annotation_scope=annotations_scope,skip_defaults=True)
            for parameter in getattr(node, "type_params", ()):
                visit(parameter, definition_scope)
            if getattr(node, "returns", None):visit(node.returns, annotations_scope,syntax_only=future_annotations)
            body = node.body if not isinstance(node, ast.Lambda) else [node.body]
            for statement in body:visit(statement, body_scope)
            return
        if isinstance(node, ast.ClassDef):
            body_scope = child_scope(node, scope, node.name, "class")
            for field in ("bases", "keywords", "decorator_list", "type_params"):
                for value in getattr(node, field, ()):visit(value, scope)
            previous_private = private_owner[0]
            private_owner[0] = node.name
            for statement in node.body:visit(statement, body_scope)
            private_owner[0] = previous_private
            return
        if isinstance(node, ast.arguments):
            for name,value in ast.iter_fields(node):
                if skip_defaults and name in {"defaults","kw_defaults"}:continue
                owner = defaults_scope if name in {"defaults","kw_defaults"} and defaults_scope is not None else scope
                for child in value if isinstance(value,list) else [value]:
                    if isinstance(child,ast.AST):visit(child,owner,annotation_scope=annotation_scope)
            return
        if isinstance(node, ast.arg):
            if node.annotation:visit(node.annotation, annotation_scope if annotation_scope is not None else scope,syntax_only=future_annotations)
            return
        if isinstance(node,ast.AnnAssign):
            visit(node.target,scope)
            inactive=future_annotations or not node.simple or scopes[scope].kind=="function"
            visit(node.annotation,scope,syntax_only=inactive)
            if node.value is not None:visit(node.value,scope)
            return
        if isinstance(node,(ast.ListComp,ast.SetComp,ast.DictComp)):
            body_scope=inline_scope(node,scope)
            for index,generator in enumerate(node.generators):
                visit(generator,body_scope,first_iter_scope=scope if index==0 else body_scope)
            if isinstance(node,ast.DictComp):
                # The official table visits value before key. This is only
                # metadata matching; the AST's key/value evaluation is intact.
                visit(node.value,body_scope);visit(node.key,body_scope)
            else:visit(node.elt,body_scope)
            return
        if isinstance(node, ast.GeneratorExp):
            # A generator in this outer iterable is a sibling official scope,
            # and precedes the containing generator even on the same line.
            visit(node.generators[0].iter,scope)
            body_scope = child_scope(node, scope, "genexpr", "function")
            generator_scopes.add(body_scope)
            for index,generator in enumerate(node.generators):
                visit(generator, body_scope, first_iter_scope=scope if index==0 else body_scope,skip_iter=index==0)
            visit(node.elt, body_scope)
            return
        if isinstance(node, ast.comprehension):
            if not skip_iter:visit(node.iter, first_iter_scope if first_iter_scope is not None else scope)
            visit(node.target, scope)
            for value in node.ifs:visit(value,scope)
            return
        if isinstance(node,ast.NamedExpr):
            visit(node.value,scope)
            visit(node.target,scope,namespace=walrus_scope(scope))
            return
        for child in ast.iter_child_nodes(node):visit(child, scope)
    definitions[id(tree)] = 0
    visit(tree)
    # Resolve owners after seeing all declarations, including assignments that
    # occur later in a function and walrus stores executed inside a comp scope.
    for name,role,scope,ordinal,namespace in pending_bindings:
        where=scope if namespace is None else namespace
        if role!="load"and scopes[where].kind!="comprehension":
            symbol=symbols[where].get(name)
            if symbol and (symbol.has("local")or symbol.has("parameter"))and not symbol.has("free")and not symbol.has("nonlocal")and not symbol.has("declared_global"):
                declarations.setdefault(where,set()).add(name)
    for name,role,scope,ordinal,namespace in pending_bindings:
        owner=scope_owner(scope if namespace is None else namespace,name)
        bindings.append(Binding(name,role,scope,owner,ordinal))
    # Logical metadata does not expose a comp-only target as an enclosing local.
    # The original symtable and the IDs of all its scopes remain untouched.
    for index,targets in inline_targets.items():
        remove=targets-declarations.get(index,set())
        scopes[index]=replace(scopes[index],symbols=tuple(symbol for symbol in scopes[index].symbols
            if symbol.name not in remove or not symbol.has("local")or symbol.has("parameter")))
    for index in range(official_count,len(scopes)):
        values={symbol.name:symbol.flags for symbol in scopes[index].symbols}
        for binding in bindings:
            if binding.scope==index:
                flags=set(values.get(binding.name,()))
                if binding.owner==index:flags.add("local")
                else:flags.add("global"if binding.owner==0 else"free")
                flags.add("referenced"if binding.role=="load"else"assigned")
                values[binding.name]=frozenset(flags)
            elif binding.owner==index:
                values[binding.name]=values.get(binding.name,frozenset())|{"comp_cell"}
        scopes[index]=replace(scopes[index],symbols=tuple(Symbol(name,flags)for name,flags in values.items()))
    children={index:[]for index in range(len(scopes))}
    for scope in scopes:
        if scope.parent is not None:children[scope.parent].append(scope.ordinal)
    scopes=tuple(replace(scope,children=tuple(children[scope.ordinal]))for scope in scopes)
    return scopes,tuple(nodes), tuple(bindings), MappingProxyType(ordinals), MappingProxyType(definitions), MappingProxyType(names),frozenset(annotation_syntax)


def parse_source(source, filename="<input>", *, name="__main__", package=False):
    """Parse and validate one unit once; no user code is evaluated."""
    try:
        tree = ast.parse(source, filename=filename)
        table = symtable.symtable(source, filename, "exec")
        compiled = compile(tree, filename, "exec", dont_inherit=True, optimize=0)
    except (SyntaxError, ValueError, RecursionError) as error:
        raise CompilationError(Diagnostic(getattr(error, "msg", str(error)), filename,
            getattr(error, "lineno", 1) or 1, getattr(error, "offset", 1) or 1, "E001")) from None
    scopes, _ = _scope_metadata(table)
    scopes,nodes, bindings, ordinals, definitions, names,annotation_syntax = _source_metadata(
        tree,scopes,future_annotations=bool(compiled.co_flags & __future__.annotations.compiler_flag))
    unit=SourceUnit(source, filename, name, package, _freeze_tree(tree), table,
                      compiled.co_flags & _FUTURE_MASK, scopes, nodes, bindings, (), frozenset(), ordinals, definitions, names, MappingProxyType({}))
    from .call_semantics import FunctionSignature
    signatures={id(node):FunctionSignature.from_unit(node,unit) for node in ast.walk(unit.tree)
                if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.Lambda))and id(node)not in annotation_syntax}
    return replace(unit,function_signatures=MappingProxyType(signatures))


class _Resolver:
    def __init__(self, filename, module_paths):
        self.paths = tuple(Path(value) for value in module_paths) or (Path(filename).resolve().parent,)
        self.modules = {}
        self.units = {}
        self.order = []

    def fail(self, name, unit, node):
        raise CompilationError(Diagnostic(f"module {name!r} is not supported or could not be found", unit.filename,
            getattr(node, "lineno", 1), getattr(node, "col_offset", 0) + 1, "E003"))

    def find(self, name):
        parent_name, _, leaf = name.rpartition(".")
        parent = self.modules.get(parent_name)
        roots = parent.search_paths if parent else self.paths
        namespaces = []
        for root in roots:
            base = root / leaf
            package = base / "__init__.py"
            if package.is_file():return Module(name, "user", str(package), True, (base,))
            path = base.with_suffix(".py")
            if path.is_file():return Module(name, "user", str(path), False)
            if base.is_dir():namespaces.append(base)
        if namespaces:return Module(name, "namespace", None, True, tuple(namespaces))
        return None

    def load(self, name, unit, node):
        if name in self.modules:return self.modules[name]
        parent_name = name.rpartition(".")[0]
        parent = self.load(parent_name, unit, node) if parent_name else None
        # The parent initializer can recursively import this very child.
        if name in self.modules:return self.modules[name]
        if parent and not parent.package and not (parent.origin == "builtin" and name in BUILTIN_MODULES):
            self.fail(name, unit, node)
        module = self.find(name)
        if module is None:
            if parent and parent.origin != "builtin":self.fail(name, unit, node)
            if name in VENDORED_MODULES:module = Module(name, "vendored", f"<pytors-stdlib>/{name}.py", False)
            elif name in BUILTIN_MODULES:module = Module(name, "builtin", None, name == "string")
            else:self.fail(name, unit, node)
        self.modules[name] = module
        if module.origin == "builtin" or module.origin == "namespace":return module
        try:
            if module.origin == "vendored":
                content = files("py2fastrust").joinpath("stdlib", name + ".py").read_bytes()
                encoding, _ = tokenize.detect_encoding(io.BytesIO(content).readline)
                source = content.decode(encoding)
            else:
                with tokenize.open(module.filename) as stream:source = stream.read()
        except SyntaxError as error:
            raise CompilationError(Diagnostic(error.msg,module.filename,1,1,"E001")) from None
        except (OSError,UnicodeError,LookupError) as error:
            message = getattr(error,"strerror",None) or str(error)
            raise CompilationError(Diagnostic(f"could not read module {name!r}: {message}",module.filename,1,1,"E005")) from None
        parsed = parse_source(source, module.filename, name=name, package=module.package)
        self.units[name] = parsed
        self.order.append(name)
        self.scan(parsed)
        return module

    def scan(self, unit):
        imports = []
        def visit(node, private=None):
            if isinstance(node, ast.ClassDef):
                private = node.name
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                def mangled(name):
                    return private_name(name,private)
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        name = mangled(alias.name)
                        module = self.load(name, unit, node)
                        imports.append(ResolvedImport(unit.ordinal(node), name, (), 0, module.origin, module.filename))
                else:
                    name = mangled(node.module or "")
                    if node.level:
                        package = unit.name if unit.package else unit.name.rpartition(".")[0]
                        parts = package.split(".") if package else []
                        if node.level > len(parts):
                            raise CompilationError(Diagnostic("relative import beyond top-level package", unit.filename,
                                node.lineno, node.col_offset + 1, "E003"))
                        name = ".".join(parts[:len(parts)-node.level+1] + ([name] if name else []))
                    module = self.load(name, unit, node)
                    children = []
                    for alias in node.names:
                        child = name + "." + alias.name
                        if alias.name != "*" and module.package and self.find(child):
                            self.load(child, unit, node)
                            children.append(child)
                    imports.append(ResolvedImport(unit.ordinal(node), name, tuple(alias.name for alias in node.names),
                        node.level, module.origin, module.filename, tuple(children)))
            for child in ast.iter_child_nodes(node):visit(child, private)
        visit(unit.tree)
        self.units[unit.name] = replace(unit, imports=tuple(imports))


def build_program(source, filename="<input>", module_paths=(), include_modules=()):
    resolver = _Resolver(filename, module_paths)
    main = parse_source(source, filename)
    resolver.units[main.name] = main
    resolver.order.append(main.name)
    resolver.scan(main)
    for name in include_modules:resolver.load(name, main, main.tree)
    unsafe = {name for name,module in resolver.modules.items() if module.origin not in {"builtin","vendored"}}
    while True:
        before = len(unsafe)
        for name,unit in resolver.units.items():
            if name in resolver.modules and any(item.module in unsafe or any(child in unsafe for child in item.children) for item in unit.imports):
                unsafe.add(name)
        if len(unsafe)==before:break
    trusted = frozenset(name for name,module in resolver.modules.items()
                        if module.origin in {"builtin","vendored"} and name not in unsafe)
    units = tuple(replace(resolver.units[name], native_imports=trusted) for name in resolver.order)
    locations = []
    scope_offset = 0
    for unit in units:
        counters = [0] * len(unit.scopes)
        for node in unit.nodes:
            if not node.located:
                continue
            locations.append(SourceLocation(scope_offset + node.scope, counters[node.scope], unit.filename, node.line, node.column))
            counters[node.scope] += 1
        scope_offset += len(unit.scopes)
    return Program(units[0], units, tuple(resolver.modules.values()), tuple(locations))


def native_namespace_diagnostic(unit):
    """Shared proof boundary for assumptions about module/builtin namespaces.

    These are valid Python bindings, not frontend syntax errors. Until emitted
    functions model mutable global namespaces, every direct emitter must reject
    such writes, including aliases that are not represented by ast.Name stores.
    """
    for binding in unit.bindings:
        if (binding.name in {"__name__","__builtins__"} and binding.owner == 0
                and binding.role not in {"load","parameter"}):
            node=unit.nodes[binding.node]
            return Diagnostic(f"direct Rust generation for rebinding {binding.name!r} is not implemented",
                              unit.filename,node.line,node.column,"E006")
    return None
