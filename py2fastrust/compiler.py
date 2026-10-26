"""Compile the official Python AST to source-located executable instructions."""

import ast
import __future__
import symtable
import tokenize
from importlib.resources import files
from pathlib import Path

from .diagnostics import CompilationError, Diagnostic
from .ir import Code, Instruction, Parameters, Pattern, Program


BUILTIN_MODULES = {
    "sys", "math", "heapq", "bisect", "collections", "itertools", "functools",
    "builtins", "operator", "types", "typing", "string", "string.templatelib",
    "gc", "time", "_py2fastrust_functools", "__future__",
}
VENDORED_MODULES = {"heapq", "bisect", "collections", "functools", "__future__"}
FUTURE_ANNOTATIONS = __future__.annotations.compiler_flag
FUTURE_MASK = sum(getattr(__future__, name).compiler_flag for name in __future__.all_feature_names) & ~0x10
BINARY = {
    ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/", ast.FloorDiv: "//",
    ast.Mod: "%", ast.Pow: "**", ast.LShift: "<<", ast.RShift: ">>",
    ast.BitAnd: "&", ast.BitOr: "|", ast.BitXor: "^", ast.MatMult: "@",
}
COMPARE = {
    ast.Eq: "==", ast.NotEq: "!=", ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">",
    ast.GtE: ">=", ast.Is: "is", ast.IsNot: "is not", ast.In: "in", ast.NotIn: "not in",
}


def clean_docstring(value):
    # CPython 3.14 Python/compile.c, _PyCompile_CleanDoc (PSF license):
    # expand tabs, remove indentation, and retain blank lines/source offsets.
    lines = value.expandtabs().split("\n")
    margin = min((len(line) - len(line.lstrip(" ")) for line in lines[1:]
                  if line.strip(" ")), default=0)
    lines[0] = lines[0].lstrip(" ")
    if margin:
        lines[1:] = [line[min(margin, len(line) - len(line.lstrip(" "))):]
                     for line in lines[1:]]
    return "\n".join(lines)


class Compiler:
    def __init__(self, filename="<input>", module_paths=(), include_modules=()):
        self.filename = filename
        self.module_paths = tuple(Path(p) for p in module_paths) or (Path(filename).resolve().parent,)
        self.include_modules = include_modules
        self.program = Program()
        self.module_ids = {}
        self.file_modules = {filename: "__main__"}
        self.temp_id = 0
        self.future_flags = {}
        # Native imports require the actual resolver provenance, not a module name.
        self.native_imports = set()

    def parse(self, source, filename):
        try:
            tree = ast.parse(source, filename=filename)
            table = symtable.symtable(source, filename, "exec")
            # ast.parse alone accepts contextually invalid return/yield/break.
            compiled = compile(source, filename, "exec", dont_inherit=True, optimize=0)
        except SyntaxError as exc:
            raise CompilationError(Diagnostic(exc.msg, filename, exc.lineno or 1, exc.offset or 1, "E001")) from None
        except ValueError as exc:
            raise CompilationError(Diagnostic(str(exc), filename, 1, 1, "E001")) from None
        self.future_flags[filename] = compiled.co_flags & FUTURE_MASK
        return tree, table

    def compile(self, source):
        tree, table = self.parse(source, self.filename)
        emitter = self.scope(tree, table, "__main__", "Module", self.filename)
        emitter.setup_scope_annotations(tree)
        emitter.module_statements(tree.body)
        emitter.finish()
        # Runtime exec/compile may contain a future statement even when the
        # static source does not import the module itself.
        self.load_module("__future__", tree, self.filename)
        for name in self.include_modules:
            self.load_module(name, tree, self.filename)
        return self.program

    def stringify_annotation(self, expression):
        if isinstance(expression, ast.Starred):
            wrapped = ast.Tuple(elts=[expression], ctx=ast.Load())
            # A tuple permits a starred expression in this inert annotation;
            # the official printer supplies its exact precedence/parentheses.
            return self.stringify_annotation(wrapped)[1:-2]
        # The official compiler's expression printer differs from ast.unparse
        # for e.g. sole generator arguments. Compile only an inert stringized
        # annotation and read its constant; no user expression is executed.
        stub = ast.Module(body=[
            ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
            ast.AnnAssign(target=ast.Name(id="_annotation", ctx=ast.Store()),
                          annotation=expression, value=None, simple=1),
        ], type_ignores=[])
        code = compile(ast.fix_missing_locations(stub), self.filename, "exec", dont_inherit=True)
        return next(value for value in code.co_consts if isinstance(value, str))

    def scope(self, node, table, name, kind, filename):
        symbols = table.get_symbols()
        local_names = [s.get_name() for s in symbols if s.is_local() or s.is_parameter()]
        if kind in {"Function", "Comprehension", "TypeParameters"}:
            parameters = {s.get_name() for s in symbols if s.is_parameter()}
            cells = {s.get_name() for s in symbols if s.is_comp_cell()}
            for child in table.get_children():
                cells.update(s.get_name() for s in child.get_symbols()
                             if s.is_free() or s.is_free_class())
            cells.intersection_update(local_names)
            cells.difference_update(parameters)
            # CPython's optimized locals expose ordinary locals first, then
            # nonparameter cells in name order, followed by the free variables.
            local_names = [name for name in local_names if name not in cells] + sorted(cells)
        code = Code(name, filename, kind,
                    locals=local_names,
                    globals=[s.get_name() for s in symbols if s.is_declared_global()],
                    nonlocals=[s.get_name() for s in symbols if s.is_nonlocal()],
                    frees=[s.get_name() for s in symbols if s.is_free()],
                    future_flags=self.future_flags.get(filename, 0))
        if kind in {"Module", "Class", "Function"} and isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            docstring = ast.get_docstring(node, clean=False)
            if docstring is not None and any(0xD800 <= ord(char) <= 0xDFFF for char in docstring):
                first = node.body[0]
                raise CompilationError(Diagnostic("unpaired Unicode surrogates are not supported", filename,
                                                 getattr(first, "lineno", 1), getattr(first, "col_offset", 0) + 1, "E002"))
            code.docstring = clean_docstring(docstring) if docstring is not None else None
        code_id = len(self.program.codes)
        self.program.codes.append(code)
        emitter = Emitter(self, code_id, table)
        if kind in {"Module", "Class"}:
            class ScopeAnnotations(ast.NodeVisitor):
                def __init__(self):
                    self.depth = 0
                    self.any_annotation = False
                    self.annotations = []

                def visit_FunctionDef(self, function):
                    pass

                visit_AsyncFunctionDef = visit_FunctionDef
                visit_ClassDef = visit_FunctionDef
                visit_Lambda = visit_FunctionDef

                def visit_AnnAssign(self, annotation):
                    self.any_annotation = True
                    if annotation.simple and isinstance(annotation.target, ast.Name):
                        self.annotations.append((annotation, kind == "Module" or self.depth > 0))

                def generic_visit(self, node):
                    conditional = isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While,
                                                    ast.With, ast.AsyncWith, ast.Try, ast.TryStar, ast.Match))
                    self.depth += conditional
                    super().generic_visit(node)
                    self.depth -= conditional
            scoped = ScopeAnnotations()
            for statement in getattr(node, "body", ()):
                scoped.visit(statement)
            if not code.future_flags & FUTURE_ANNOTATIONS:
                emitter.scope_annotations = scoped.annotations
                emitter.has_scope_annotation = scoped.any_annotation
                index = 0
                for annotation, conditional in scoped.annotations:
                    if conditional:
                        emitter.annotation_indices[id(annotation)] = index
                        index += 1
        if code.future_flags & FUTURE_ANNOTATIONS and kind in {"Module", "Class"}:
            class Annotations(ast.NodeVisitor):
                found = False

                def visit_AnnAssign(self, annotation):
                    self.found = True

                def visit_FunctionDef(self, function):
                    pass

                visit_AsyncFunctionDef = visit_FunctionDef
                visit_ClassDef = visit_FunctionDef
                visit_Lambda = visit_FunctionDef
            annotations = Annotations()
            for statement in getattr(node, "body", ()):
                annotations.visit(statement)
            if annotations.found:
                if kind == "Module":
                    emitter.emit("BuildSet", 0, node=node)
                    emitter.emit("Store", "__conditional_annotations__", node=node)
                    emitter.emit("SetupAnnotations", node=node)
                else:
                    emitter.annotation_setup_pending = True
        return emitter

    def find_module(self, name):
        parts = name.split(".")
        for root in self.module_paths:
            base = root.joinpath(*parts)
            for path in (base.with_suffix(".py"), base / "__init__.py"):
                if path.is_file():
                    return path
        return None

    def load_module(self, name, node, filename):
        if not name or name in self.module_ids:
            return
        path = self.find_module(name)
        if path is None and name in VENDORED_MODULES:
            path = Path(str(files("py2fastrust").joinpath("stdlib", name + ".py")))
            self.native_imports.add(name)
        if path is None and name in BUILTIN_MODULES:
            return
        if path is None:
            raise CompilationError(Diagnostic(f"module {name!r} is not supported or could not be found", filename,
                                             getattr(node, "lineno", 1), getattr(node, "col_offset", 0) + 1, "E003"))
        if "." in name:
            self.load_module(name.rsplit(".", 1)[0], node, filename)
        with tokenize.open(path) as stream:
            source = stream.read()
        tree, table = self.parse(source, str(path))
        self.file_modules[str(path)] = name
        emitter = self.scope(tree, table, name, "Module", str(path))
        self.module_ids[name] = emitter.code_id
        self.program.modules.append((name, emitter.code_id))
        emitter.setup_scope_annotations(tree)
        emitter.module_statements(tree.body)
        emitter.finish()


class Emitter:
    def module_statements(self, body):
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
            self.emit("Const", clean_docstring(body[0].value.value), node=body[0])
            self.emit("Store", "__doc__", node=body[0])
            body = body[1:]
        self.statements(body)

    def __init__(self, compiler, code_id, table):
        self.compiler = compiler
        self.code_id = code_id
        self.code = compiler.program.codes[code_id]
        self.table = table
        self.used_scopes = set()
        self.scope_owner = self
        self.loops = []
        self.enclosing = None
        self.private_class = None
        self.annotation_setup_pending = False
        self.scope_annotations = []
        self.has_scope_annotation = False
        self.annotation_indices = {}

    def mangle(self, name):
        if (self.private_class and name is not None and name.startswith("__")
                and not name.endswith("__") and "." not in name):
            owner = self.private_class.lstrip("_")
            if owner:
                return "_" + owner + name
        return name

    def set_private(self, name):
        self.private_class = name
        # Synthetic comprehension symbol tables are produced outside the
        # lexical class. Apply the same idempotent transformation to them.
        for field in ("locals", "globals", "nonlocals", "frees"):
            setattr(self.code, field, [self.mangle(item) for item in getattr(self.code, field)])

    def emit(self, op, *args, node=None):
        if op in {"Load", "Store", "Delete", "GetAttr", "GetSpecialAttr", "SetAttr", "DelAttr"}:
            args = (self.mangle(args[0]), *args[1:])
        self.code.ops.append(Instruction(op, args, getattr(node, "lineno", 1), getattr(node, "col_offset", 0) + 1))
        return len(self.code.ops) - 1

    def patch(self, index, target=None):
        self.code.ops[index].args = (len(self.code.ops) if target is None else target,)

    def temp(self):
        name = f"$tmp{self.compiler.temp_id}"
        self.compiler.temp_id += 1
        self.code.locals.append(name)
        return name

    def fail(self, node, message=None):
        raise CompilationError(Diagnostic(message or f"unsupported syntax: {type(node).__name__}",
                                         self.code.filename, getattr(node, "lineno", 1),
                                         getattr(node, "col_offset", 0) + 1, "E002"))

    def child(self, node, name, kind="Function"):
        owner = self.scope_owner
        candidates = [table for table in owner.table.get_children()
                      if table.get_id() not in owner.used_scopes and table.get_name() == name]
        for table in sorted(candidates, key=lambda t: t.get_lineno() != node.lineno):
            if table.get_id() not in owner.used_scopes and table.get_name() == name and table.get_lineno() == node.lineno:
                owner.used_scopes.add(table.get_id())
                child = self.compiler.scope(node, table, name, kind, self.code.filename)
                child.enclosing = self
                child.set_private(node.name if kind == "Class" or kind == "TypeParameters" and isinstance(node, ast.ClassDef) else self.private_class)
                self.inherit_child_frees(child)
                return child
        if len(candidates) == 1:
            table = candidates[0]
            owner.used_scopes.add(table.get_id())
            child = self.compiler.scope(node, table, name, kind, self.code.filename)
            child.enclosing = self
            child.set_private(node.name if kind == "Class" or kind == "TypeParameters" and isinstance(node, ast.ClassDef) else self.private_class)
            self.inherit_child_frees(child)
            return child
        self.fail(node, f"could not associate the official symbol table with {name}")

    def inherit_child_frees(self, child):
        # Inlined comprehensions share their lexical owner's official child
        # scopes. Keep their transitive captures on the synthetic IR frames.
        for name in child.code.frees:
            scope = self
            while scope.scope_owner is not scope:
                if name in scope.code.locals or name in scope.code.globals:
                    break
                if name not in scope.code.frees:
                    scope.code.frees.append(name)
                scope = scope.enclosing

    def visit(self, node):
        method = getattr(self, f"visit_{type(node).__name__}", None)
        if method is None:
            self.fail(node)
        return method(node)

    def statements(self, nodes):
        for node in nodes:
            self.visit(node)

    def finish(self):
        self.emit("Const", None)
        self.emit("Return")

    def store(self, node):
        if isinstance(node, ast.Name):
            name = self.mangle(node.id)
            self.code.bindings[name] = self.code.bindings.get(name, 0) + 1
            self.emit("Store", node.id, node=node)
        elif isinstance(node, (ast.Tuple, ast.List)):
            stars = [i for i, elt in enumerate(node.elts) if isinstance(elt, ast.Starred)]
            if stars:
                self.emit("UnpackEx", stars[0], len(node.elts) - stars[0] - 1, node=node)
            else:
                self.emit("Unpack", len(node.elts), node=node)
            for elt in node.elts:
                self.store(elt.value if isinstance(elt, ast.Starred) else elt)
        elif isinstance(node, ast.Subscript):
            self.visit(node.value)
            self.visit(node.slice)
            self.emit("SetItem", node=node)
        elif isinstance(node, ast.Attribute):
            self.visit(node.value)
            self.emit("SetAttr", node.attr, node=node)
        else:
            self.fail(node, "unsupported assignment target")

    def visit_Constant(self, node):
        if node.value is Ellipsis:
            self.emit("Load", "Ellipsis", node=node)
        elif isinstance(node.value, (type(None), bool, int, float, complex, str, bytes)):
            if isinstance(node.value, str) and any(0xD800 <= ord(char) <= 0xDFFF for char in node.value):
                self.fail(node, "unpaired Unicode surrogates are not supported")
            self.emit("Const", node.value, node=node)
        else:
            self.fail(node, f"unsupported constant type: {type(node.value).__name__}")

    def visit_Name(self, node):
        if node.id == "__debug__":
            self.emit("Const", True, node=node)
        else:
            self.emit("Load", node.id, node=node)

    def visit_Expr(self, node):
        self.visit(node.value)
        self.emit("Pop", node=node)

    def visit_Pass(self, node):
        self.emit("Nop", node=node)

    def visit_Assign(self, node):
        self.visit(node.value)
        for target in node.targets[:-1]:
            self.emit("Dup", node=node)
            self.store(target)
        self.store(node.targets[-1])

    def visit_AnnAssign(self, node):
        if node.value is not None:
            self.visit(node.value)
            self.store(node.target)
        elif isinstance(node.target, ast.Attribute):
            self.visit(node.target.value)
            self.emit("Pop", node=node)
        elif isinstance(node.target, ast.Subscript):
            self.visit(node.target.value)
            self.emit("Pop", node=node)
            self.visit(node.target.slice)
            self.emit("Pop", node=node)
        if (self.code.future_flags & FUTURE_ANNOTATIONS
                and self.code.kind in {"Module", "Class"}
                and node.simple and isinstance(node.target, ast.Name)):
            self.emit("Const", self.compiler.stringify_annotation(node.annotation), node=node.annotation)
            self.emit("Load", "__annotations__", node=node)
            self.emit("Const", self.mangle(node.target.id), node=node)
            self.emit("SetItem", node=node)
        elif id(node) in self.annotation_indices:
            self.emit("LoadCell" if self.code.kind == "Class" else "Load", "__conditional_annotations__", node=node)
            self.emit("Const", self.annotation_indices[id(node)], node=node)
            self.emit("SetAdd", 1, node=node)
            self.emit("Pop", node=node)

    def setup_scope_annotations(self, node):
        if self.code.kind == "Module":
            self.finish_scope_annotations(node)
            if self.has_scope_annotation:
                self.emit("BuildSet", 0, node=node)
                self.emit("Store", "__conditional_annotations__", node=node)
        elif self.annotation_indices:
            self.emit("BuildSet", 0, node=node)
            self.emit("StoreCell", "__conditional_annotations__", node=node)

    def finish_scope_annotations(self, node):
        if not self.scope_annotations:
            return
        anchor = ast.Constant(value=None, lineno=self.scope_annotations[0][0].lineno, col_offset=0)
        helper = self.child(anchor, "__annotate__", "Annotation")
        helper.code.params = Parameters(posonly=1, positional=[".format"])
        if self.code.kind == "Class" and self.annotation_indices and "__conditional_annotations__" not in helper.code.frees:
            helper.code.frees.append("__conditional_annotations__")
        helper.emit("Load", ".format", node=anchor)
        helper.emit("Const", 2, node=anchor)
        helper.emit("Compare", ">", node=anchor)
        valid = helper.emit("JumpFalse", 0, node=anchor)
        helper.emit("Load", "NotImplementedError", node=anchor)
        helper.emit("Call", 0, [], node=anchor)
        helper.emit("Raise", 1, node=anchor)
        helper.patch(valid)
        helper.emit("BuildDict", 0, node=anchor)
        for annotation, _ in self.scope_annotations:
            skipped = None
            if id(annotation) in self.annotation_indices:
                helper.emit("Const", self.annotation_indices[id(annotation)], node=annotation)
                helper.emit("LoadCell" if self.code.kind == "Class" else "Load", "__conditional_annotations__", node=annotation)
                helper.emit("Compare", "in", node=annotation)
                skipped = helper.emit("JumpFalse", 0, node=annotation)
            helper.emit("Dup", node=annotation)
            helper.visit(annotation.annotation)
            helper.emit("Swap", node=annotation)
            helper.emit("Const", self.mangle(annotation.target.id), node=annotation)
            helper.emit("SetItem", node=annotation)
            if skipped is not None:
                helper.patch(skipped)
        helper.emit("Return", node=anchor)
        self.emit("MakeFunction", helper.code_id, 0, [], node=anchor)
        self.emit("Store", "__annotate_func__" if self.code.kind == "Class" else "__annotate__", node=anchor)

    def visit_NamedExpr(self, node):
        self.visit(node.value)
        self.emit("Dup", node=node)
        self.store(node.target)

    def visit_AugAssign(self, node):
        target = node.target
        if isinstance(target, ast.Name):
            self.visit(target)
            self.visit(node.value)
            self.emit("Binary", "i" + BINARY[type(node.op)], node=node)
            self.store(target)
        elif isinstance(target, ast.Subscript):
            obj, idx = self.temp(), self.temp()
            self.visit(target.value)
            self.emit("Store", obj, node=node)
            self.visit(target.slice)
            self.emit("Store", idx, node=node)
            self.emit("Load", obj, node=node)
            self.emit("Load", idx, node=node)
            self.emit("GetItem", node=node)
            self.visit(node.value)
            self.emit("Binary", "i" + BINARY[type(node.op)], node=node)
            self.emit("Load", obj, node=node)
            self.emit("Load", idx, node=node)
            self.emit("SetItem", node=node)
        elif isinstance(target, ast.Attribute):
            obj = self.temp()
            self.visit(target.value)
            self.emit("Store", obj, node=node)
            self.emit("Load", obj, node=node)
            self.emit("GetAttr", target.attr, node=node)
            self.visit(node.value)
            self.emit("Binary", "i" + BINARY[type(node.op)], node=node)
            self.emit("Load", obj, node=node)
            self.emit("SetAttr", target.attr, node=node)
        else:
            self.fail(node)

    def visit_Delete(self, node):
        for target in node.targets:
            if isinstance(target, ast.Name):
                self.emit("Delete", target.id, node=node)
            elif isinstance(target, ast.Subscript):
                self.visit(target.value)
                self.visit(target.slice)
                self.emit("DelItem", node=node)
            elif isinstance(target, ast.Attribute):
                self.visit(target.value)
                self.emit("DelAttr", target.attr, node=node)
            elif isinstance(target, (ast.Tuple, ast.List)):
                self.visit_Delete(ast.copy_location(ast.Delete(targets=target.elts), node))
            else:
                self.fail(target)

    def visit_BinOp(self, node):
        self.visit(node.left)
        self.visit(node.right)
        self.emit("Binary", BINARY[type(node.op)], node=node)

    def visit_UnaryOp(self, node):
        self.visit(node.operand)
        self.emit("Unary", {ast.UAdd: "+", ast.USub: "-", ast.Invert: "~", ast.Not: "not"}[type(node.op)], node=node)

    def visit_BoolOp(self, node):
        jumps = []
        for value in node.values[:-1]:
            self.visit(value)
            self.emit("Dup", node=node)
            jumps.append(self.emit("JumpFalse" if isinstance(node.op, ast.And) else "JumpTrue", 0, node=node))
            self.emit("Pop", node=node)
        self.visit(node.values[-1])
        for jump in jumps:
            self.patch(jump)

    def visit_Compare(self, node):
        if len(node.ops) == 1:
            self.visit(node.left)
            self.visit(node.comparators[0])
            self.emit("Compare", COMPARE[type(node.ops[0])], node=node)
            return
        left, right = self.temp(), self.temp()
        self.visit(node.left)
        self.emit("Store", left, node=node)
        jumps = []
        for i, (op, comparator) in enumerate(zip(node.ops, node.comparators)):
            self.visit(comparator)
            self.emit("Store", right, node=node)
            self.emit("Load", left, node=node)
            self.emit("Load", right, node=node)
            self.emit("Compare", COMPARE[type(op)], node=node)
            if i + 1 < len(node.ops):
                self.emit("Dup", node=node)
                jumps.append(self.emit("JumpFalse", 0, node=node))
                self.emit("Pop", node=node)
                self.emit("Load", right, node=node)
                self.emit("Store", left, node=node)
        for jump in jumps:
            self.patch(jump)

    def visit_IfExp(self, node):
        self.visit(node.test)
        other = self.emit("JumpFalse", 0, node=node)
        self.visit(node.body)
        end = self.emit("Jump", 0, node=node)
        self.patch(other)
        self.visit(node.orelse)
        self.patch(end)

    def visit_If(self, node):
        self.visit(node.test)
        other = self.emit("JumpFalse", 0, node=node)
        self.statements(node.body)
        end = self.emit("Jump", 0, node=node)
        self.patch(other)
        self.statements(node.orelse)
        self.patch(end)

    def pattern_path(self, node):
        if isinstance(node, ast.Name):
            return [self.mangle(node.id)]
        if isinstance(node, ast.Attribute):
            return self.pattern_path(node.value) + [self.mangle(node.attr)]
        self.fail(node, "pattern value must be a literal or dotted name")

    def value_pattern(self, node):
        if isinstance(node, (ast.Name, ast.Attribute)):
            return Pattern("ValuePath", (self.pattern_path(node),))
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)):
            # Keep integer components intact until the runtime applies the
            # selected width. Folding to a host complex would lose that step.
            try:
                real = ast.literal_eval(node.left)
                imaginary = ast.literal_eval(node.right)
            except (ValueError, TypeError):
                self.fail(node, "unsupported pattern constant")
            if type(real) in (int, float) and isinstance(imaginary, complex) and imaginary.real == 0:
                imag = imaginary.imag if isinstance(node.op, ast.Add) else -imaginary.imag
                return Pattern("ComplexNumber", (real, imag))
        try:
            value = ast.literal_eval(node)
        except (ValueError, TypeError):
            self.fail(node, "unsupported pattern constant")
        return Pattern("Literal", (value,))

    def pattern(self, node):
        if isinstance(node, ast.MatchValue):
            return self.value_pattern(node.value)
        if isinstance(node, ast.MatchSingleton):
            return Pattern("Literal", (node.value,))
        if isinstance(node, ast.MatchSequence):
            return Pattern("Sequence", ([self.pattern(p) for p in node.patterns],))
        if isinstance(node, ast.MatchMapping):
            return Pattern("Mapping", ([self.value_pattern(k) for k in node.keys],
                                       [self.pattern(p) for p in node.patterns], self.mangle(node.rest)))
        if isinstance(node, ast.MatchClass):
            return Pattern("Class", (self.pattern_path(node.cls), [self.pattern(p) for p in node.patterns],
                                     node.kwd_attrs, [self.pattern(p) for p in node.kwd_patterns]))
        if isinstance(node, ast.MatchAs):
            return Pattern("As", (self.pattern(node.pattern) if node.pattern is not None else None, self.mangle(node.name)))
        if isinstance(node, ast.MatchStar):
            return Pattern("Star", (self.mangle(node.name),))
        if isinstance(node, ast.MatchOr):
            return Pattern("Or", ([self.pattern(p) for p in node.patterns],))
        self.fail(node, "unsupported match pattern")

    def visit_Match(self, node):
        subject = self.temp()
        self.visit(node.subject)
        self.emit("Store", subject, node=node)
        ends = []
        for case in node.cases:
            self.emit("Load", subject, node=node)
            self.emit("Match", self.pattern(case.pattern), node=case.pattern)
            skips = [self.emit("JumpFalse", 0, node=case.pattern)]
            if case.guard is not None:
                self.visit(case.guard)
                skips.append(self.emit("JumpFalse", 0, node=case.guard))
            self.statements(case.body)
            ends.append(self.emit("Jump", 0, node=node))
            for jump in skips:
                self.patch(jump)
        for jump in ends:
            self.patch(jump)

    def loop(self, node, is_for):
        if is_for:
            self.visit(node.iter)
            self.emit("GetIter", node=node)
        start = len(self.code.ops)
        if is_for:
            exhausted = self.emit("ForIter", 0, node=node)
            self.store(node.target)
        else:
            self.visit(node.test)
            exhausted = self.emit("JumpFalse", 0, node=node)
        context = {"breaks": [], "continue": start}
        self.loops.append(context)
        self.statements(node.body)
        self.loops.pop()
        self.emit("Jump", start, node=node)
        self.patch(exhausted)
        self.statements(node.orelse)
        bypass = self.emit("Jump", 0, node=node)
        for jump in context["breaks"]:
            self.patch(jump)
        if is_for:
            self.emit("Pop", node=node)
        self.patch(bypass)

    def visit_For(self, node):
        self.loop(node, True)

    def visit_While(self, node):
        self.loop(node, False)

    def visit_Break(self, node):
        if not self.loops:
            self.fail(node, "break outside loop")
        self.loops[-1]["breaks"].append(self.emit("Break", 0, node=node))

    def visit_Continue(self, node):
        if not self.loops:
            self.fail(node, "continue outside loop")
        self.emit("Continue", self.loops[-1]["continue"], node=node)

    def sequence(self, node, kind):
        if any(isinstance(elt, ast.Starred) for elt in node.elts):
            for elt in node.elts:
                self.visit(elt.value if isinstance(elt, ast.Starred) else elt)
                if not isinstance(elt, ast.Starred):
                    self.emit("BuildTuple", 1, node=elt)
                else:
                    self.emit("BuildListUnpack", 1, node=elt)
            self.emit(f"Build{kind}Unpack", len(node.elts), node=node)
        else:
            for elt in node.elts:
                self.visit(elt)
            self.emit(f"Build{kind}", len(node.elts), node=node)

    def visit_List(self, node):
        self.sequence(node, "List")

    def visit_Tuple(self, node):
        self.sequence(node, "Tuple")

    def visit_Set(self, node):
        if any(isinstance(elt, ast.Starred) for elt in node.elts):
            self.emit("BuildSet", 0, node=node)
            for elt in node.elts:
                if isinstance(elt, ast.Starred):
                    self.visit(elt.value)
                    self.emit("GetIter", node=elt)
                    start = len(self.code.ops)
                    end = self.emit("ForIter", 0, node=elt)
                    self.emit("SetAdd", 2, node=elt)
                    self.emit("Jump", start, node=elt)
                    self.patch(end)
                else:
                    self.visit(elt)
                    self.emit("SetAdd", 1, node=elt)
        else:
            self.sequence(node, "Set")

    def visit_Dict(self, node):
        if all(key is not None for key in node.keys):
            for key, value in zip(node.keys, node.values):
                self.visit(key)
                self.visit(value)
            self.emit("BuildDict", len(node.keys), node=node)
        else:
            self.emit("BuildDict", 0, node=node)
            for key, value in zip(node.keys, node.values):
                if key is not None:
                    self.visit(key)
                    self.visit(value)
                    self.emit("BuildDict", 1, node=node)
                else:
                    self.visit(value)
                self.emit("Binary", "dict_merge", node=node)

    def visit_Subscript(self, node):
        self.visit(node.value)
        self.visit(node.slice)
        self.emit("GetItem", node=node)

    def visit_Slice(self, node):
        for part in (node.lower, node.upper, node.step):
            self.visit(part) if part is not None else self.emit("Const", None, node=node)
        self.emit("BuildSlice", 3, node=node)

    def visit_Attribute(self, node):
        self.visit(node.value)
        self.emit("GetAttr", node.attr, node=node)

    def visit_Call(self, node):
        self.visit(node.func)
        expanded = any(isinstance(arg, ast.Starred) for arg in node.args) or any(k.arg is None for k in node.keywords)
        if not expanded:
            for arg in node.args:
                self.visit(arg)
            for keyword in node.keywords:
                self.visit(keyword.value)
            self.emit("Call", len(node.args), [k.arg for k in node.keywords], node=node)
            return
        for arg in node.args:
            self.visit(arg.value if isinstance(arg, ast.Starred) else arg)
            if not isinstance(arg, ast.Starred):
                self.emit("BuildTuple", 1, node=arg)
            elif len(node.args) > 1:
                self.emit("BuildTupleUnpack", 1, node=arg)
        if not (len(node.args) == 1 and isinstance(node.args[0], ast.Starred)):
            self.emit("BuildTupleUnpack", len(node.args), node=node)
        if node.keywords:
            self.expanded_keywords(node.keywords, node)
        self.emit("CallEx", bool(node.keywords), node=node)

    def expanded_keywords(self, keywords, anchor):
        self.emit("BuildDict", 0, node=anchor)
        index = 0
        while index < len(keywords):
            keyword = keywords[index]
            if keyword.arg is None:
                self.visit(keyword.value)
                index += 1
            else:
                start = index
                while index < len(keywords) and keywords[index].arg is not None:
                    item = keywords[index]
                    self.emit("Keyword", item.arg, node=item.value)
                    self.visit(item.value)
                    index += 1
                self.emit("BuildDict", index - start, node=keyword.value)
            self.emit("Binary", "kwargs_merge", node=keyword.value)

    def set_params(self, emitter, args):
        emitter.code.params = Parameters(len(args.posonlyargs),
                                        [emitter.mangle(a.arg) for a in args.posonlyargs + args.args],
                                        [emitter.mangle(a.arg) for a in args.kwonlyargs],
                                        emitter.mangle(args.vararg.arg) if args.vararg else None,
                                        emitter.mangle(args.kwarg.arg) if args.kwarg else None)

    def make_function(self, node, name, body, decorators=(), type_scope=False):
        if getattr(node, "type_params", ()) and not type_scope:
            return self.generic_function(node, name, body, decorators)
        for decorator in decorators:
            self.visit(decorator)
        for index, default in enumerate(node.args.defaults):
            if type_scope:
                self.emit("Load", ".defaults", node=default)
                self.emit("Const", index, node=default)
                self.emit("GetItem", node=default)
            else:
                self.visit(default)
        kwdefaults = []
        for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
            if default is not None:
                kwdefaults.append(self.mangle(arg.arg))
                if type_scope:
                    self.emit("Load", ".kwdefaults", node=default)
                    self.emit("Const", self.mangle(arg.arg), node=default)
                    self.emit("GetItem", node=default)
                else:
                    self.visit(default)
        emitter = self.child(node, name)
        self.set_params(emitter, node.args)
        if isinstance(node, ast.Lambda):
            emitter.visit(body)
            emitter.emit("Return", node=node)
        else:
            emitter.statements(body)
        emitter.finish()
        self.emit("MakeFunction", emitter.code_id, len(node.args.defaults), kwdefaults, node=node)
        self.function_annotations(node)
        for decorator in reversed(decorators):
            self.emit("Call", 1, [], node=decorator)

    def type_parameter_scope(self, node, name):
        wrapper = self.child(node, name, "TypeParameters")
        wrapper.code.name = f"<generic parameters of {name}>"
        if ".type_params" not in wrapper.code.locals:
            wrapper.code.locals.append(".type_params")
        return wrapper

    def evaluation_thunk(self, node, name, expression):
        thunk = self.child(node, name, "Annotation")
        thunk.code.params = Parameters(posonly=1, positional=[".format"])
        thunk.emit("Load", ".format", node=node)
        thunk.emit("Const", 2, node=node)
        thunk.emit("Compare", ">", node=node)
        valid = thunk.emit("JumpFalse", 0, node=node)
        thunk.emit("Load", "NotImplementedError", node=node)
        thunk.emit("Call", 0, [], node=node)
        thunk.emit("Raise", 1, node=node)
        thunk.patch(valid)
        if isinstance(expression, ast.Starred):
            thunk.visit(expression.value)
            thunk.emit("TypeUnpack", node=expression)
        else:
            thunk.visit(expression)
        thunk.emit("Return", node=node)
        self.emit("Const", 1, node=node)
        self.emit("MakeFunction", thunk.code_id, 1, [], node=node)

    def type_parameters(self, node):
        for parameter in node.type_params:
            bound = getattr(parameter, "bound", None)
            constraints = isinstance(bound, ast.Tuple)
            for expression in (bound if not constraints else None,
                               bound if constraints else None,
                               parameter.default_value):
                if expression is None:
                    self.emit("Const", None, node=parameter)
                else:
                    self.evaluation_thunk(parameter, parameter.name, expression)
            kind = {ast.TypeVar: "typevar", ast.ParamSpec: "paramspec", ast.TypeVarTuple: "typevartuple"}[type(parameter)]
            self.emit("MakeTypeParam", parameter.name, kind, node=parameter)
            self.emit("Store", parameter.name, node=parameter)
        for parameter in node.type_params:
            self.emit("Load", parameter.name, node=parameter)
        self.emit("BuildTuple", len(node.type_params), node=node)
        self.emit("Store", ".type_params", node=node)

    def generic_function(self, node, name, body, decorators):
        for decorator in decorators:
            self.visit(decorator)
        wrapper = self.type_parameter_scope(node, name)
        parameters = []
        if node.args.defaults:
            parameters.append(".defaults")
        kwdefaults = [(arg, default) for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults)
                      if default is not None]
        if kwdefaults:
            parameters.append(".kwdefaults")
        wrapper.code.params = Parameters(posonly=len(parameters), positional=parameters)
        wrapper.type_parameters(node)
        wrapper.make_function(node, name, body, type_scope=True)
        wrapper.emit("Dup", node=node)
        wrapper.emit("Load", ".type_params", node=node)
        wrapper.emit("Swap", node=node)
        wrapper.emit("SetAttr", "__type_params__", node=node)
        wrapper.emit("Return", node=node)
        self.emit("MakeFunction", wrapper.code_id, 0, [], node=node)
        if node.args.defaults:
            for default in node.args.defaults:
                self.visit(default)
            self.emit("BuildTuple", len(node.args.defaults), node=node)
        if kwdefaults:
            for arg, default in kwdefaults:
                self.emit("Const", self.mangle(arg.arg), node=arg)
                self.visit(default)
            self.emit("BuildDict", len(kwdefaults), node=node)
        self.emit("Call", len(parameters), [], node=node)
        for decorator in reversed(decorators):
            self.emit("Call", 1, [], node=decorator)

    def visit_TypeAlias(self, node):
        name = node.name.id
        if node.type_params:
            wrapper = self.type_parameter_scope(node, name)
            wrapper.type_parameters(node)
            wrapper.emit("Load", ".type_params", node=node)
            wrapper.evaluation_thunk(node, name, node.value)
            wrapper.emit("MakeTypeAlias", name, node=node)
            wrapper.emit("Return", node=node)
            self.emit("MakeFunction", wrapper.code_id, 0, [], node=node)
            self.emit("Call", 0, [], node=node)
        else:
            self.emit("BuildTuple", 0, node=node)
            self.evaluation_thunk(node, name, node.value)
            self.emit("MakeTypeAlias", name, node=node)
        self.emit("Store", name, node=node)

    def function_annotations(self, node):
        arguments = node.args.posonlyargs + node.args.args
        if node.args.vararg:
            arguments += [node.args.vararg]
        arguments += node.args.kwonlyargs
        if node.args.kwarg:
            arguments += [node.args.kwarg]
        annotations = [(self.mangle(arg.arg), arg.annotation) for arg in arguments if arg.annotation is not None]
        if getattr(node, "returns", None) is not None:
            annotations.append(("return", node.returns))
        if not annotations:
            return
        stringized = self.code.future_flags & FUTURE_ANNOTATIONS
        if stringized:
            # Future annotations have no annotation child in the official
            # symbol table. Their helper contains strings and captures no names.
            code_id = len(self.compiler.program.codes)
            self.compiler.program.codes.append(Code("__annotate__", self.code.filename, "Annotation",
                                                    future_flags=self.code.future_flags))
            annotate = Emitter(self.compiler, code_id, self.table)
        else:
            annotate = self.child(node, "__annotate__", "Annotation")
        annotate.code.params = Parameters(posonly=1, positional=[".format"])
        annotate.emit("Load", ".format", node=node)
        annotate.emit("Const", 2, node=node)
        annotate.emit("Compare", ">", node=node)
        valid = annotate.emit("JumpFalse", 0, node=node)
        annotate.emit("Load", "NotImplementedError", node=node)
        annotate.emit("Call", 0, [], node=node)
        annotate.emit("Raise", 1, node=node)
        annotate.patch(valid)
        for name, expression in annotations:
            annotate.emit("Const", name, node=expression)
            if stringized:
                annotate.emit("Const", self.compiler.stringify_annotation(expression), node=expression)
            elif isinstance(expression, ast.Starred):
                annotate.visit(expression.value)
                annotate.emit("TypeUnpack", node=expression)
            else:
                annotate.visit(expression)
        annotate.emit("BuildDict", len(annotations), node=node)
        annotate.emit("Return", node=node)
        self.emit("Dup", node=node)
        self.emit("MakeFunction", annotate.code_id, 0, [], node=node)
        self.emit("Swap", node=node)
        self.emit("SetAttr", "__annotate__", node=node)

    def visit_FunctionDef(self, node):
        self.make_function(node, node.name, node.body, node.decorator_list)
        self.emit("Store", node.name, node=node)

    def visit_Lambda(self, node):
        self.make_function(node, "lambda", node.body)

    def visit_Return(self, node):
        self.visit(node.value) if node.value else self.emit("Const", None, node=node)
        self.emit("Return", node=node)

    def visit_Yield(self, node):
        self.code.is_generator = True
        self.visit(node.value) if node.value else self.emit("Const", None, node=node)
        self.emit("Yield", node=node)

    def visit_YieldFrom(self, node):
        self.code.is_generator = True
        self.visit(node.value)
        self.emit("GetYieldFromIter", node=node)
        self.emit("YieldFrom", node=node)

    def visit_ClassDef(self, node, type_scope=False):
        if node.type_params and not type_scope:
            for decorator in node.decorator_list:
                self.visit(decorator)
            wrapper = self.type_parameter_scope(node, node.name)
            wrapper.type_parameters(node)
            wrapper.visit_ClassDef(node, type_scope=True)
            wrapper.emit("Return", node=node)
            self.emit("MakeFunction", wrapper.code_id, 0, [], node=node)
            self.emit("Call", 0, [], node=node)
            for decorator in reversed(node.decorator_list):
                self.emit("Call", 1, [], node=decorator)
            self.emit("Store", node.name, node=node)
            return
        for decorator in (() if type_scope else node.decorator_list):
            self.visit(decorator)
        expanded = any(isinstance(base, ast.Starred) for base in node.bases) or any(
            keyword.arg is None for keyword in node.keywords
        )
        for base in node.bases:
            self.visit(base.value if isinstance(base, ast.Starred) else base)
            if expanded:
                self.emit("BuildTupleUnpack" if isinstance(base, ast.Starred) else "BuildTuple", 1, node=base)
        if type_scope:
            self.emit("Load", ".type_params", node=node)
            self.emit("GenericBase", node=node)
            if expanded:
                self.emit("BuildTuple", 1, node=node)
        if expanded:
            self.emit("BuildTupleUnpack", len(node.bases) + int(type_scope), node=node)
            self.expanded_keywords(node.keywords, node)
        else:
            for keyword in node.keywords:
                self.visit(keyword.value)
        emitter = self.child(node, node.name, "Class")
        first_line = min([node.lineno] + [decorator.lineno for decorator in node.decorator_list])
        emitter.emit("Const", first_line, node=node)
        emitter.emit("Store", "__firstlineno__", node=node)
        if type_scope:
            emitter.emit("Load", ".type_params", node=node)
            emitter.emit("Store", "__type_params__", node=node)
        if emitter.annotation_setup_pending:
            emitter.emit("SetupAnnotations", node=node)
        emitter.setup_scope_annotations(node)
        body = node.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
            emitter.emit("Const", clean_docstring(body[0].value.value), node=body[0])
            emitter.emit("Store", "__doc__", node=body[0])
            body = body[1:]
        emitter.statements(body)
        emitter.finish_scope_annotations(node)
        attributes = set()
        class StaticAttributes(ast.NodeVisitor):
            def visit_ClassDef(self, nested):
                pass

            def visit_AugAssign(self, assignment):
                self.visit(assignment.value)

            def visit_AnnAssign(self, assignment):
                if assignment.value is not None:
                    self.visit(assignment.target)
                    self.visit(assignment.value)

            def visit_Attribute(self, attribute):
                if (isinstance(attribute.ctx, ast.Store) and isinstance(attribute.value, ast.Name)
                        and attribute.value.id == "self"):
                    attributes.add(attribute.attr)
                self.generic_visit(attribute)
        for statement in body:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                StaticAttributes().visit(statement)
        for attribute in sorted(attributes):
            emitter.emit("Const", attribute, node=node)
        emitter.emit("BuildTuple", len(attributes), node=node)
        emitter.emit("Store", "__static_attributes__", node=node)
        emitter.finish()
        if expanded:
            self.emit("MakeClassEx", node.name, emitter.code_id, node=node)
        else:
            self.emit("MakeClass", node.name, emitter.code_id, len(node.bases) + int(type_scope), [k.arg for k in node.keywords], node=node)
        for decorator in reversed(() if type_scope else node.decorator_list):
            self.emit("Call", 1, [], node=decorator)
        if not type_scope:
            self.emit("Store", node.name, node=node)

    def visit_Global(self, node):
        pass

    def visit_Nonlocal(self, node):
        pass

    def visit_Raise(self, node):
        if node.exc is not None:
            self.visit(node.exc)
        if node.cause is not None:
            self.visit(node.cause)
        self.emit("Raise", int(node.exc is not None) + int(node.cause is not None), node=node)

    def visit_Assert(self, node):
        self.visit(node.test)
        end = self.emit("JumpTrue", 0, node=node)
        self.emit("Load", "AssertionError", node=node)
        if node.msg:
            self.visit(node.msg)
        self.emit("Call", int(node.msg is not None), [], node=node)
        self.emit("Raise", 1, node=node)
        self.patch(end)

    def try_except(self, node):
        handler = self.emit("SetupExcept", 0, node=node)
        self.statements(node.body)
        self.emit("PopHandler", node=node)
        self.statements(node.orelse)
        end = [self.emit("Jump", 0, node=node)]
        self.patch(handler)
        for clause in node.handlers:
            skip = None
            if clause.type is not None:
                self.emit("LoadException", node=clause)
                self.visit(clause.type)
                self.emit("ExceptionMatch", node=clause)
                skip = self.emit("JumpFalse", 0, node=clause)
            if clause.name:
                self.emit("LoadException", node=clause)
                self.emit("Store", clause.name, node=clause)
            cleanup = self.emit("SetupFinally", 0, node=clause)
            self.statements(clause.body)
            self.emit("PopHandler", node=clause)
            normal = self.emit("Jump", 0, node=clause)
            self.patch(cleanup)
            self.patch(normal)
            if clause.name:
                self.emit("Const", None, node=clause)
                self.emit("Store", clause.name, node=clause)
                self.emit("Delete", clause.name, node=clause)
            self.emit("ClearException", node=clause)
            self.emit("EndFinally", node=clause)
            end.append(self.emit("Jump", 0, node=clause))
            if skip is not None:
                self.patch(skip)
        self.emit("Raise", 0, node=node)
        for jump in end:
            self.patch(jump)

    def try_except_star(self, node):
        handler = self.emit("SetupExcept", 0, node=node)
        self.statements(node.body)
        self.emit("PopHandler", node=node)
        self.statements(node.orelse)
        normal = self.emit("Jump", 0, node=node)
        self.patch(handler)
        state = self.temp()
        self.emit("BeginExceptStar", node=node)
        self.emit("Store", state, node=node)
        state_cleanup = self.emit("SetupFinally", 0, node=node)
        for clause in node.handlers:
            self.emit("Load", state, node=clause)
            self.visit(clause.type)
            self.emit("SplitExceptStar", node=clause)
            skip = self.emit("JumpFalse", 0, node=clause)
            if clause.name:
                self.emit("LoadException", node=clause)
                self.emit("Store", clause.name, node=clause)
            failed = self.emit("SetupExcept", 0, node=clause)
            self.statements(clause.body)
            self.emit("PopHandler", node=clause)
            if clause.name:
                self.emit("Const", None, node=clause)
                self.emit("Store", clause.name, node=clause)
                self.emit("Delete", clause.name, node=clause)
            self.emit("Load", state, node=clause)
            self.emit("RecordExceptStar", False, node=clause)
            recorded = self.emit("Jump", 0, node=clause)
            self.patch(failed)
            self.emit("Load", state, node=clause)
            self.emit("RecordExceptStar", True, node=clause)
            if clause.name:
                self.emit("Const", None, node=clause)
                self.emit("Store", clause.name, node=clause)
                self.emit("Delete", clause.name, node=clause)
            self.patch(recorded)
            self.patch(skip)
        self.emit("Load", state, node=node)
        self.emit("EndExceptStar", node=node)
        self.emit("PopHandler", node=node)
        self.patch(state_cleanup)
        self.emit("Delete", state, node=node)
        self.emit("EndFinally", node=node)
        self.patch(normal)

    def visit_Try(self, node):
        final = self.emit("SetupFinally", 0, node=node) if node.finalbody else None
        if node.handlers:
            if isinstance(node, ast.TryStar):
                self.try_except_star(node)
            else:
                self.try_except(node)
        else:
            self.statements(node.body)
        if final is not None:
            self.emit("PopHandler", node=node)
            jump = self.emit("Jump", 0, node=node)
            self.patch(final)
            self.patch(jump)
            self.statements(node.finalbody)
            self.emit("EndFinally", node=node)

    visit_TryStar = visit_Try

    def visit_With(self, node):
        item = node.items[0]
        manager, exit_method, needed, entered = self.temp(), self.temp(), self.temp(), self.temp()
        self.visit(item.context_expr)
        self.emit("Store", manager, node=node)
        self.emit("Load", manager, node=node)
        self.emit("GetSpecialAttr", "__exit__", node=node)
        self.emit("Store", exit_method, node=node)
        self.emit("Load", manager, node=node)
        self.emit("GetSpecialAttr", "__enter__", node=node)
        self.emit("Call", 0, [], node=node)
        self.emit("Store", entered, node=node)
        self.emit("Const", True, node=node)
        self.emit("Store", needed, node=node)
        final = self.emit("SetupFinally", 0, node=node)
        handler = self.emit("SetupExcept", 0, node=node)
        self.emit("Load", entered, node=node)
        self.store(item.optional_vars) if item.optional_vars else self.emit("Pop", node=node)
        if len(node.items) > 1:
            nested = ast.copy_location(ast.With(items=node.items[1:], body=node.body, type_comment=None), node)
            self.visit_With(nested)
        else:
            self.statements(node.body)
        self.emit("PopHandler", node=node)
        normal = self.emit("Jump", 0, node=node)
        self.patch(handler)
        self.emit("Const", False, node=node)
        self.emit("Store", needed, node=node)
        self.emit("Load", exit_method, node=node)
        self.emit("LoadExceptionType", node=node)
        self.emit("LoadException", node=node)
        self.emit("LoadExceptionTraceback", node=node)
        self.emit("Call", 3, [], node=node)
        suppressed = self.emit("JumpTrue", 0, node=node)
        self.emit("Raise", 0, node=node)
        self.patch(suppressed)
        self.emit("ClearException", node=node)
        self.patch(normal)
        self.emit("PopHandler", node=node)
        jump = self.emit("Jump", 0, node=node)
        self.patch(final)
        self.patch(jump)
        self.emit("Load", needed, node=node)
        skip = self.emit("JumpFalse", 0, node=node)
        self.emit("Load", exit_method, node=node)
        for _ in range(3):
            self.emit("Const", None, node=node)
        self.emit("Call", 3, [], node=node)
        self.emit("Pop", node=node)
        self.patch(skip)
        self.emit("EndFinally", node=node)

    def comprehension(self, node, name, kind):
        # First-iterator scopes belong to the enclosing lexical scope and are
        # visited before the comprehension body by the official symbol table.
        self.visit(node.generators[0].iter)
        self.emit("GetIter", node=node)
        if kind == "Generator":
            emitter = self.child(node, name, "Comprehension")
        else:
            # PEP 709 inlines list/set/dict comprehensions in CPython's symbol
            # table. A generator has the same isolated bindings and exposes
            # those bindings through the official symtable API.
            element = (ast.Tuple(elts=[node.key, node.value], ctx=ast.Load())
                       if kind == "Dict" else node.elt)
            equivalent = ast.GeneratorExp(elt=element, generators=node.generators)
            source = "\n" * (node.lineno - 1) + ast.unparse(ast.fix_missing_locations(equivalent))
            table = next(t for t in symtable.symtable(source, self.code.filename, "exec").get_children()
                         if t.get_name() == "genexpr")
            emitter = self.compiler.scope(node, table, name, "Comprehension", self.code.filename)
            emitter.enclosing = self
            emitter.scope_owner = self.scope_owner
            emitter.set_private(self.private_class)
            emitter.code.globals = [name for name in emitter.code.globals
                                    if name not in self.code.locals and name not in self.code.nonlocals]
            for symbol in table.get_symbols():
                name = emitter.mangle(symbol.get_name())
                if symbol.is_local() or name in emitter.code.globals:
                    continue
                scope = self
                while scope is not None and scope.code.kind != "Module":
                    if name in scope.code.globals:
                        break
                    if scope.code.kind != "Class" and name in scope.code.locals:
                        if name not in emitter.code.frees:
                            emitter.code.frees.append(name)
                        break
                    scope = scope.enclosing
        # PEP 572 binds comprehension walrus targets in the enclosing ordinary
        # scope, including targets that have not yet received a value there.
        targets = []
        class Walrus(ast.NodeVisitor):
            def visit_Lambda(self, expr):
                pass

            def visit_NamedExpr(self, expr):
                targets.append(expr.target.id)
                self.visit(expr.value)
        Walrus().visit(node)
        owner = self
        while owner.code.kind == "Comprehension" and owner.enclosing is not None:
            owner = owner.enclosing
        for target in map(emitter.mangle, targets):
            global_target = owner.code.kind == "Module" or target in owner.code.globals
            destination = emitter.code.globals if global_target else emitter.code.nonlocals
            other = emitter.code.nonlocals if global_target else emitter.code.globals
            if target in other:
                other.remove(target)
            if target not in destination:
                destination.append(target)
            if not global_target and target not in owner.code.locals:
                owner.code.locals.append(target)
        emitter.code.params = Parameters(positional=[".0"])
        result = emitter.temp()
        if kind != "Generator":
            emitter.emit(f"Build{kind}", 0, node=node)
            emitter.emit("Store", result, node=node)
        def generate(level):
            gen = node.generators[level]
            if gen.is_async:
                emitter.fail(node, "async comprehensions are not implemented")
            if level == 0:
                emitter.emit("Load", ".0", node=node)
            else:
                emitter.visit(gen.iter)
                emitter.emit("GetIter", node=node)
            start = len(emitter.code.ops)
            end = emitter.emit("ForIter", 0, node=node)
            emitter.store(gen.target)
            skips = []
            for condition in gen.ifs:
                emitter.visit(condition)
                skips.append(emitter.emit("JumpFalse", start, node=condition))
            if level + 1 < len(node.generators):
                generate(level + 1)
            elif kind == "Dict":
                key = emitter.temp()
                emitter.visit(node.key)
                emitter.emit("Store", key, node=node)
                emitter.visit(node.value)
                emitter.emit("Load", result, node=node)
                emitter.emit("Load", key, node=node)
                emitter.emit("SetItem", node=node)
            elif kind == "Generator":
                emitter.code.is_generator = True
                emitter.visit(node.elt)
                emitter.emit("Yield", node=node)
                emitter.emit("Pop", node=node)
            else:
                emitter.emit("Load", result, node=node)
                emitter.emit("GetAttr", "append" if kind == "List" else "add", node=node)
                emitter.visit(node.elt)
                emitter.emit("Call", 1, [], node=node)
                emitter.emit("Pop", node=node)
            emitter.emit("Jump", start, node=node)
            emitter.patch(end)
        generate(0)
        if kind != "Generator":
            emitter.emit("Load", result, node=node)
            emitter.emit("Return", node=node)
        emitter.finish()
        self.emit("MakeFunction", emitter.code_id, 0, [], node=node)
        self.emit("Swap", node=node)
        self.emit("Call", 1, [], node=node)

    def visit_ListComp(self, node):
        self.comprehension(node, "listcomp", "List")

    def visit_SetComp(self, node):
        self.comprehension(node, "setcomp", "Set")

    def visit_DictComp(self, node):
        self.comprehension(node, "dictcomp", "Dict")

    def visit_GeneratorExp(self, node):
        self.comprehension(node, "genexpr", "Generator")

    def visit_JoinedStr(self, node):
        for value in node.values:
            self.visit(value)
        self.emit("BuildString", len(node.values), node=node)

    def visit_TemplateStr(self, node):
        for value in node.values:
            self.visit(value)
        self.emit("BuildTemplate", len(node.values), node=node)

    def visit_Interpolation(self, node):
        self.visit(node.value)
        if node.format_spec is not None:
            self.visit(node.format_spec)
        self.emit("MakeInterpolation", node.str, node.conversion,
                  node.format_spec is not None, node=node)

    def visit_FormattedValue(self, node):
        self.visit(node.value)
        if node.format_spec:
            self.visit(node.format_spec)
        self.emit("FormatValue", node.conversion, node.format_spec is not None, node=node)

    def absolute_import(self, module, level):
        if not level:
            return module
        name = self.compiler.file_modules.get(self.code.filename, "__main__")
        package = name if Path(self.code.filename).name == "__init__.py" else name.rpartition(".")[0]
        parts = package.split(".") if package else []
        if level > len(parts):
            self.fail(ast.Constant(value=None), "relative import beyond top-level package")
        return ".".join(parts[:len(parts) - level + 1] + ([module] if module else []))

    def visit_Import(self, node):
        for alias in node.names:
            module = self.mangle(alias.name)
            self.compiler.load_module(module, node, self.code.filename)
            self.emit("Import", module, ["*"] if alias.asname else [], 0, node=node)
            self.emit("Store", alias.asname or alias.name.split(".")[0], node=node)

    def visit_ImportFrom(self, node):
        module = self.absolute_import(self.mangle(node.module or ""), node.level)
        self.compiler.load_module(module, node, self.code.filename)
        for alias in node.names:
            if self.compiler.find_module(f"{module}.{alias.name}"):
                self.compiler.load_module(f"{module}.{alias.name}", node, self.code.filename)
        self.emit("Import", module, [a.name for a in node.names], 0, node=node)
        for alias in node.names:
            if alias.name == "*":
                self.emit("ImportFrom", "*", node=node)
                self.emit("Pop", node=node)
                return
            self.emit("ImportFrom", self.mangle(alias.name), node=node)
            self.emit("Store", alias.asname or alias.name, node=node)
        self.emit("Pop", node=node)
