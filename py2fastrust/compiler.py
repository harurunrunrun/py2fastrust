"""Compile the official Python AST to source-located executable instructions."""

import ast
import symtable
import tokenize
from pathlib import Path

from .diagnostics import CompilationError, Diagnostic
from .ir import Code, Instruction, Parameters, Program


BUILTIN_MODULES = {
    "sys", "math", "heapq", "bisect", "collections", "itertools", "functools",
    "builtins", "operator", "types",
}
BINARY = {
    ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/", ast.FloorDiv: "//",
    ast.Mod: "%", ast.Pow: "**", ast.LShift: "<<", ast.RShift: ">>",
    ast.BitAnd: "&", ast.BitOr: "|", ast.BitXor: "^", ast.MatMult: "@",
}
COMPARE = {
    ast.Eq: "==", ast.NotEq: "!=", ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">",
    ast.GtE: ">=", ast.Is: "is", ast.IsNot: "is not", ast.In: "in", ast.NotIn: "not in",
}


class Compiler:
    def __init__(self, filename="<input>", module_paths=(), include_modules=()):
        self.filename = filename
        self.module_paths = tuple(Path(p) for p in module_paths) or (Path(filename).resolve().parent,)
        self.include_modules = include_modules
        self.program = Program()
        self.module_ids = {}
        self.file_modules = {filename: "__main__"}
        self.temp_id = 0

    def parse(self, source, filename):
        try:
            tree = ast.parse(source, filename=filename)
            table = symtable.symtable(source, filename, "exec")
            # ast.parse alone accepts contextually invalid return/yield/break.
            compile(source, filename, "exec", dont_inherit=True)
        except SyntaxError as exc:
            raise CompilationError(Diagnostic(exc.msg, filename, exc.lineno or 1, exc.offset or 1, "E001")) from None
        return tree, table

    def compile(self, source):
        tree, table = self.parse(source, self.filename)
        emitter = self.scope(tree, table, "__main__", "Module", self.filename)
        emitter.statements(tree.body)
        emitter.finish()
        for name in self.include_modules:
            self.load_module(name, tree, self.filename)
        return self.program

    def scope(self, node, table, name, kind, filename):
        symbols = table.get_symbols()
        code = Code(name, filename, kind,
                    locals=[s.get_name() for s in symbols if s.is_local() or s.is_parameter()],
                    globals=[s.get_name() for s in symbols if s.is_global()],
                    nonlocals=[s.get_name() for s in symbols if s.is_nonlocal()])
        code_id = len(self.program.codes)
        self.program.codes.append(code)
        return Emitter(self, code_id, table)

    def find_module(self, name):
        parts = name.split(".")
        for root in self.module_paths:
            base = root.joinpath(*parts)
            for path in (base.with_suffix(".py"), base / "__init__.py"):
                if path.is_file():
                    return path
        return None

    def load_module(self, name, node, filename):
        if not name or name.split(".")[0] in BUILTIN_MODULES or name in self.module_ids:
            return
        path = self.find_module(name)
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
        emitter.statements(tree.body)
        emitter.finish()


class Emitter:
    def __init__(self, compiler, code_id, table):
        self.compiler = compiler
        self.code_id = code_id
        self.code = compiler.program.codes[code_id]
        self.table = table
        self.used_scopes = set()
        self.loops = []

    def emit(self, op, *args, node=None):
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
        candidates = [table for table in self.table.get_children()
                      if table.get_id() not in self.used_scopes and table.get_name() == name]
        for table in sorted(candidates, key=lambda t: t.get_lineno() != node.lineno):
            if table.get_id() not in self.used_scopes and table.get_name() == name and table.get_lineno() == node.lineno:
                self.used_scopes.add(table.get_id())
                return self.compiler.scope(node, table, name, kind, self.code.filename)
        if len(candidates) == 1:
            table = candidates[0]
            self.used_scopes.add(table.get_id())
            return self.compiler.scope(node, table, name, kind, self.code.filename)
        self.fail(node, f"could not associate the official symbol table with {name}")

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
            self.code.bindings[node.id] = self.code.bindings.get(node.id, 0) + 1
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
        elif isinstance(node.value, (type(None), bool, int, float, str, bytes)):
            self.emit("Const", node.value, node=node)
        else:
            self.fail(node, "complex constants are not implemented")

    def visit_Name(self, node):
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
            self.emit("Load", "set", node=node)
            self.sequence(node, "List")
            self.emit("Call", 1, [], node=node)
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
        self.emit("BuildTupleUnpack", len(node.args), node=node)
        if node.keywords:
            self.emit("BuildDict", 0, node=node)
            for keyword in node.keywords:
                if keyword.arg is not None:
                    self.emit("Const", keyword.arg, node=node)
                    self.visit(keyword.value)
                    self.emit("BuildDict", 1, node=node)
                else:
                    self.visit(keyword.value)
                self.emit("Binary", "kwargs_merge", node=node)
        self.emit("CallEx", bool(node.keywords), node=node)

    def set_params(self, emitter, args):
        emitter.code.params = Parameters(len(args.posonlyargs),
                                        [a.arg for a in args.posonlyargs + args.args],
                                        [a.arg for a in args.kwonlyargs],
                                        args.vararg.arg if args.vararg else None,
                                        args.kwarg.arg if args.kwarg else None)

    def make_function(self, node, name, body, decorators=()):
        for decorator in decorators:
            self.visit(decorator)
        for default in node.args.defaults:
            self.visit(default)
        kwdefaults = []
        for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
            if default is not None:
                kwdefaults.append(arg.arg)
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
        for decorator in reversed(decorators):
            self.emit("Call", 1, [], node=decorator)

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

    def visit_ClassDef(self, node):
        for decorator in node.decorator_list:
            self.visit(decorator)
        for base in node.bases:
            self.visit(base)
        for keyword in node.keywords:
            if keyword.arg is None:
                self.fail(node, "expanded class keywords are not implemented")
            self.visit(keyword.value)
        emitter = self.child(node, node.name, "Class")
        emitter.statements(node.body)
        emitter.finish()
        self.emit("MakeClass", node.name, emitter.code_id, len(node.bases), [k.arg for k in node.keywords], node=node)
        for decorator in reversed(node.decorator_list):
            self.emit("Call", 1, [], node=decorator)
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
            self.statements(clause.body)
            if clause.name:
                self.emit("Delete", clause.name, node=clause)
            self.emit("ClearException", node=clause)
            end.append(self.emit("Jump", 0, node=clause))
            if skip is not None:
                self.patch(skip)
        self.emit("Raise", 0, node=node)
        for jump in end:
            self.patch(jump)

    def visit_Try(self, node):
        final = self.emit("SetupFinally", 0, node=node) if node.finalbody else None
        if node.handlers:
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

    def visit_With(self, node):
        item = node.items[0]
        manager, exit_method, needed = self.temp(), self.temp(), self.temp()
        self.visit(item.context_expr)
        self.emit("Store", manager, node=node)
        self.emit("Load", manager, node=node)
        self.emit("GetAttr", "__exit__", node=node)
        self.emit("Store", exit_method, node=node)
        self.emit("Load", manager, node=node)
        self.emit("GetAttr", "__enter__", node=node)
        self.emit("Call", 0, [], node=node)
        self.store(item.optional_vars) if item.optional_vars else self.emit("Pop", node=node)
        self.emit("Const", True, node=node)
        self.emit("Store", needed, node=node)
        final = self.emit("SetupFinally", 0, node=node)
        handler = self.emit("SetupExcept", 0, node=node)
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
        self.emit("Load", "type", node=node)
        self.emit("LoadException", node=node)
        self.emit("Call", 1, [], node=node)
        self.emit("LoadException", node=node)
        self.emit("Const", None, node=node)
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
            emitter.code.globals = [name for name in emitter.code.globals
                                    if name not in self.code.locals and name not in self.code.nonlocals]
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
        self.visit(node.generators[0].iter)
        self.emit("GetIter", node=node)
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
            self.compiler.load_module(alias.name, node, self.code.filename)
            self.emit("Import", alias.name, ["*"] if alias.asname else [], 0, node=node)
            self.emit("Store", alias.asname or alias.name.split(".")[0], node=node)

    def visit_ImportFrom(self, node):
        if node.module == "__future__":
            self.fail(node, "__future__ imports are not implemented")
        module = self.absolute_import(node.module or "", node.level)
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
            self.emit("Dup", node=node)
            self.emit("ImportFrom", alias.name, node=node)
            self.emit("Store", alias.asname or alias.name, node=node)
        self.emit("Pop", node=node)
