"""Direct, typed class lowering with compiled Rust continuations.

The proof covers a closed collection of ordinary classes and functions. Each
instance has a concrete Rust layout, and each mutable list has shared typed
storage. Rust compiles function bodies into futures; an iterative caller stack
polls them without interpreting Python operations or growing the host stack.
"""

import ast
import symtable
from dataclasses import dataclass, field
from importlib.resources import files
from types import SimpleNamespace

from .native import _Expression, _Unsupported, _direct_diagnostic, _string
from .call_semantics import FunctionSignature, CallBindingError, normalize_call
from .references import CORE_BUILTINS, BuiltinIdentity, UnknownReference, resolve_static_callable
from .native_types import (TupleType, ListType, MaybeType, NullableType, UnionType,
                           alternatives, union_type, join_types, immutable, render_type,
                           tuple_code, union_declaration)
from .native_unions import construct, project, union_kind
from .native_constraints import Solver, SemanticGraph, Variable, value as constraint_value



@dataclass(frozen=True)
class InstanceType:
    """A class-specific leaf; structural/value kinds use the shared descriptors."""
    name: str

    @property
    def _native_kind_tag(self):
        return "instance_"+self.name


@dataclass(frozen=True)
class StreamType:
    name: str
    fields: tuple = ()

    @property
    def _native_kind_tag(self):
        from .native_types import kind_tag
        return self.name+"_"+"_".join(kind_tag(value)for value in self.fields)


def domain(kind):
    if isinstance(kind, InstanceType):return "object"
    if isinstance(kind, TupleType):return "tuple"
    if isinstance(kind, ListType):return "list"
    if isinstance(kind, StreamType):return kind.name
    if union_kind(kind):return "union"
    return kind


def has_float_payload(kind):
    """Float container equality needs Python object identity, beyond f64 values."""
    if kind=="float":return True
    if isinstance(kind,(NullableType,MaybeType)):return has_float_payload(kind.value)
    if isinstance(kind,UnionType):return any(has_float_payload(value)for value in kind.alternatives)
    if isinstance(kind,TupleType):return any(has_float_payload(value)for value in kind.fields)
    if isinstance(kind,ListType):return has_float_payload(kind.element)
    return False


class ClassUnsupported(_Unsupported):
    def __init__(self, node):
        self.node = node


@dataclass(eq=False)
class Cell:
    tag: str | None = None
    args: tuple = ()
    parent: "Cell | None" = None

    def root(self):
        if self.parent is not None:
            self.parent = self.parent.root()
            return self.parent
        return self


def shape(cell):
    cell = cell.root()
    if cell.tag == "list":return ListType(shape(cell.args[0]))
    if cell.tag == "tuple":return TupleType(tuple(shape(value)for value in cell.args))
    if cell.tag == "object":return InstanceType(cell.args[0])
    if cell.tag in {"enumerate","map_int"}:return StreamType(cell.tag,tuple(shape(value)for value in cell.args))
    if cell.tag == "union":return union_type(*(shape(value)for value in cell.args))
    return cell.tag


def immutable_cell(cell):
    return immutable(shape(cell))


def merge(left, right, node):
    left, right = left.root(), right.root()
    if left is right:
        return left
    if left.tag is None:
        left.parent = right
        return right
    if right.tag is None:
        right.parent = left
        return left
    if {left.tag, right.tag} <= {"int", "bool", "int_bool"}:
        tag = join_types(left.tag,right.tag)
        right.parent = left
        left.tag = tag
        return left
    if left.tag != right.tag or left.tag=="union"or(left.tag=="tuple"and len(left.args)!=len(right.args)):
        if not immutable_cell(left)or not immutable_cell(right):raise ClassUnsupported(node)
        # Keep constructor payloads separate from the outer joined ABI. Mutable
        # allocation shapes are never widened into a union by this solver.
        candidates=[]
        for value in (left,right):
            choices=value.args if value.tag=="union"else(Cell(value.tag,value.args),)
            for choice in choices:
                if not any(shape(choice)==shape(old)for old in candidates):candidates.append(choice)
        left.tag,left.args="union",tuple(candidates)
        right.parent=left
        return left
    if left.tag in {"list", "tuple", "enumerate", "map_int"}:
        if len(left.args) != len(right.args):
            raise ClassUnsupported(node)
        for a, b in zip(left.args, right.args):
            merge(a, b, node)
    elif left.args != right.args:
        raise ClassUnsupported(node)
    right.parent = left
    return left


from .frontend import private_name as mangle


@dataclass
class Field:
    name: str
    cell: Cell = field(default_factory=Cell)
    written: bool = False


@dataclass(eq=False)
class ClassPlan:
    node: ast.ClassDef
    index: int
    methods: dict = field(default_factory=dict)
    fields: dict = field(default_factory=dict)
    used: bool = False


@dataclass(eq=False)
class FunctionPlan:
    node: ast.AST
    index: int
    owner: ClassPlan | None = None
    parameters: list = field(default_factory=list)
    positional_only: set = field(default_factory=set)
    keyword_only: list = field(default_factory=list)
    defaults: dict = field(default_factory=dict)
    default_cells: dict = field(default_factory=dict)
    default_literals: dict = field(default_factory=dict)
    signature: FunctionSignature | None = None
    arguments: dict = field(default_factory=dict)
    result: Cell = field(default_factory=Cell)
    locals: dict = field(default_factory=dict)
    declared: set = field(default_factory=set)
    reachable: bool = False
    visible_definitions: set | None = None
    global_names: set | None = None

    @property
    def scope(self):
        return self.node.name if isinstance(self.node, ast.FunctionDef) else "<module>"

    def name(self, value):
        return mangle(value, self.owner.node.name if self.owner else None)


class Environment(dict):
    """Possible typed bindings plus names definitely assigned on this path."""
    def __init__(self,values=(),*,definite=None):
        super().__init__(values)
        known=getattr(values,"definite",None)if definite is None else definite
        self.definite=set(self)if known is None else set(known)


class Model:
    BUILTINS = {"input", "print", "range", "len", "int", "bool", "str", "float",
                "list", "map", "enumerate", "sum", "min", "max", "abs", "id"}
    DATA = {"int", "bool", "int_bool", "union", "str", "bytes", "float", "none", "object", "list", "tuple", "range"}
    INTRINSICS = {"sys", "stdin", "stdin_buffer", "reader_text", "reader_bytes", "read_text", "read_bytes"}

    def __init__(self, tree, filename, integer, trusted_imports, unit=None, string_mode="ascii"):
        self.tree, self.filename, self.integer = tree, filename, integer
        self.string_mode = string_mode
        self.unit = unit
        self.trusted_imports = trusted_imports
        self.classes, self.functions = {}, {}
        self.plans = []
        self.node_cells = {}
        # Storage members receive directional value constraints. Their incoming
        # immutable values retain independent types, just as in ordinary scopes.
        self.value_constraints = Solver(SemanticGraph(unit) if unit is not None else SimpleNamespace())
        self.member_allocations = {}
        self.constructors = {}
        self.sequence_calls = {}
        self.records = {}
        self.augmented = {}
        self.module = FunctionPlan(tree, 0, reachable=True, visible_definitions=set(),global_names=set())
        merge(self.module.result, Cell("none"), tree)
        self.plans.append(self.module)
        self.loop_depth = 0
        self.loop_edges = []
        self.final = False
        self.global_symbols = {}
        # Global binding versions through loops are not represented yet.
        # A possible module-owned write forbids assuming the default builtin,
        # including a write reached only on a later loop iteration.
        self.global_written_names=frozenset(binding.name for binding in unit.bindings
            if binding.owner==0 and binding.role not in {"load","parameter"})if unit is not None else frozenset()
        self.discover()

    def resolved_name(self, plan, node):
        if self.unit is not None:return self.unit.name_for(node)
        raw=node.id if isinstance(node,ast.Name)else node.attr if isinstance(node,ast.Attribute)else node.arg
        return plan.name(raw)

    def builtin_identity(self,plan,node,environment):
        name=self.resolved_name(plan,node)
        if name in self.classes or name in self.functions:
            return UnknownReference(name,"name denotes a source definition")
        return resolve_static_callable(node,environment,local_names=plan.declared,
            global_bound_names=(set(plan.global_names or ())if plan is not self.module else set(environment))|self.global_written_names,
            name_for=self.unit.name_for if self.unit is not None else None,
            private_owner=plan.owner.node.name if plan.owner else None,function_scope=plan is not self.module)

    def cell(self, plan, node, tag=None, args=()):
        key = (plan.index, id(node))
        result = self.node_cells.setdefault(key, Cell())
        if tag is not None:
            self.constructors.setdefault(key,Cell(tag,tuple(args)))
            merge(result, Cell(tag, tuple(args)), node)
        self.records[key] = result
        if tag == "list":
            site=self.unit.ordinal(node) if self.unit is not None else id(node)
            allocation=self.value_constraints.allocation(site,"list",("class",plan.index))
            self.member_allocations[id(result.root().args[0])]=allocation
        return result

    @staticmethod
    def flow_copy(cell):
        """Copy value shapes while preserving shared mutable allocation leaves."""
        cell=cell.root()
        if cell.tag in {"list","object"}:return cell
        if cell.tag in {"tuple","union","enumerate","map_int"}:
            return Cell(cell.tag,tuple(Model.flow_copy(child)for child in cell.args))
        return Cell(cell.tag,cell.args)

    @staticmethod
    def cell_for_kind(kind):
        if isinstance(kind,NullableType):
            return Cell("union",(Cell("none"),Model.cell_for_kind(kind.value)))
        if isinstance(kind,UnionType):
            return Cell("union",tuple(Model.cell_for_kind(choice)for choice in kind.alternatives))
        if isinstance(kind,TupleType):
            return Cell("tuple",tuple(Model.cell_for_kind(child)for child in kind.fields))
        return Cell(kind)

    def contribute(self,destination,source,node):
        """A value flowing into storage never changes the source's value type."""
        source=source.root()
        if source.tag is None:return destination
        kind=shape(source)
        if immutable(kind):
            allocation=self.member_allocations.get(id(destination))
            variable=(Variable(allocation.site,"element") if allocation is not None else
                      Variable(("class_value",id(destination)),"value"))
            previous=shape(destination)
            if previous is not None and immutable(previous):
                self.value_constraints.constrain(variable,constraint_value(previous))
            if allocation is not None:
                self.value_constraints.insert(constraint_value(allocation),"element",constraint_value(kind))
            else:self.value_constraints.constrain(variable,constraint_value(kind))
            resolved=self.value_constraints.kind(constraint_value(variable))
            return merge(destination,self.cell_for_kind(resolved),node)
        return merge(destination,self.flow_copy(source),node)

    def remember(self, plan, node, result):
        self.records[(plan.index, id(node))] = result
        return result

    def field(self, owner, name, node, writing=False):
        if name in owner.methods:
            raise ClassUnsupported(node)
        if name.startswith("__") and name.endswith("__"):
            raise ClassUnsupported(node)
        result = owner.fields.setdefault(name, Field(name))
        result.written |= writing
        return result.cell

    def function(self, node, owner=None):
        if (node.decorator_list or node.returns is not None or node.type_params
                or node.args.vararg or node.args.kwarg):
            raise ClassUnsupported(node)
        arguments = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
        if any(value.annotation is not None for value in arguments):
            raise ClassUnsupported(node)
        plan = FunctionPlan(node, len(self.plans), owner)
        if self.unit is not None:
            signature=self.unit.signature_for(node)
        else:
            locals_at_definition={self.resolved_name(plan,value)for value in ast.walk(node)
                                  if isinstance(value,ast.Name)and isinstance(value.ctx,(ast.Store,ast.Del))}
            locals_at_definition.update(self.resolved_name(plan,value)for value in arguments)
            signature=FunctionSignature.from_ast(node,name_for=lambda arg:self.resolved_name(plan,arg),local_names=locals_at_definition)
        plan.signature=signature
        plan.parameters=list(signature.positional)
        plan.positional_only=set(signature.positional_only)
        plan.keyword_only=list(signature.keyword_only)
        if owner and not plan.parameters:raise ClassUnsupported(node)
        for name in signature.parameters:plan.arguments[name]=Cell()
        plan.declared=set(signature.local_names)
        defaults=[(slot.name,slot.expression)for slot in signature.defaults]
        for name, value in defaults:
            literal = value.operand if isinstance(value, ast.UnaryOp) and isinstance(value.op, (ast.UAdd, ast.USub)) else value
            if not isinstance(literal, ast.Constant) or type(literal.value) not in {int, bool, float, str, type(None)}:
                raise ClassUnsupported(value)
            plan.defaults[name] = value
            # These are total, immutable literal defaults. Capture their value
            # once at definition planning, including unused methods.
            plan.default_cells[name]=self.expression(plan,value,{})
            captured=literal.value
            if isinstance(value,ast.UnaryOp):
                captured=-captured if isinstance(value.op,ast.USub)else +captured
            plan.default_literals[name]=captured
        if owner:
            merge(plan.arguments[plan.parameters[0]], Cell("object", (owner.node.name,)), node)
        if not any(isinstance(value, ast.Return) and value.value is not None
                   and not (isinstance(value.value, ast.Constant) and value.value.value is None)
                   for value in ast.walk(node)):
            merge(plan.result, Cell("none"), node)
        self.plans.append(plan)
        return plan

    def discover(self):
        effects = False
        names = set()
        for node in self.tree.body:
            if isinstance(node, ast.ClassDef):
                if node.name in names or node.name in self.global_symbols or node.bases or node.keywords or node.decorator_list or node.type_params:
                    raise ClassUnsupported(node)
                owner = ClassPlan(node, len(self.classes))
                self.classes[node.name] = owner
                names.add(node.name)
                for member in node.body:
                    if isinstance(member, ast.Pass) or isinstance(member, ast.Expr) and isinstance(member.value, ast.Constant) and type(member.value.value) is str:
                        continue
                    if not isinstance(member, ast.FunctionDef):
                        raise ClassUnsupported(member)
                    if member.name.startswith("__") and member.name.endswith("__") and member.name != "__init__":
                        raise ClassUnsupported(member)
                    name = self.unit.name_for(member) if self.unit is not None else mangle(member.name, node.name)
                    if name in owner.methods:
                        raise ClassUnsupported(member)
                    owner.methods[name] = self.function(member, owner)
            elif isinstance(node, ast.FunctionDef):
                if node.name in names or node.name in self.global_symbols:
                    raise ClassUnsupported(node)
                self.functions[node.name] = self.function(node)
                names.add(node.name)
            elif isinstance(node, ast.Import):
                if effects or any(value.name != "sys" for value in node.names) or "sys" not in self.trusted_imports:
                    raise ClassUnsupported(node)
                for value in node.names:
                    if (value.asname or value.name)in names:raise ClassUnsupported(node)
                    self.global_symbols[value.asname or value.name] = Cell("sys")
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and type(node.value.value) is str:
                continue
            else:
                effects = True
        for value in ast.walk(self.tree):
            if isinstance(value, ast.Name) and isinstance(value.ctx, (ast.Store, ast.Del)) and value.id in names:
                raise ClassUnsupported(value)
            if isinstance(value, ast.arg) and value.arg in names:
                raise ClassUnsupported(value)

    def canonical_local(self, plan, name, value):
        values = plan.locals.setdefault(name, [])
        if not any(existing is value for existing in values):
            values.append(value)

    def snapshot(self):
        return (tuple((plan.reachable, None if plan.visible_definitions is None else tuple(sorted(plan.visible_definitions)), None if plan.global_names is None else tuple(sorted(plan.global_names)), shape(plan.result), tuple((name, shape(cell)) for name, cell in plan.arguments.items())) for plan in self.plans),
                tuple((owner.node.name, tuple((name, shape(value.cell), value.written) for name, value in owner.fields.items())) for owner in self.classes.values()),
                tuple(sorted((key, shape(value)) for key, value in self.records.items())))

    def infer_until_stable(self):
        for _ in range(96):
            before = self.snapshot()
            self.module.visible_definitions = set()
            self.block(self.module, self.tree.body, dict(self.global_symbols))
            for plan in self.plans[1:]:
                if not plan.reachable:
                    continue
                environment = {name:value for name,value in self.global_symbols.items() if name not in plan.declared}
                environment.update(plan.arguments)
                for name, value in plan.arguments.items():
                    self.canonical_local(plan, name, value)
                remaining = self.block(plan, plan.node.body, environment)
                if remaining is not None:
                    merge(plan.result, Cell("none"), plan.node)
            if self.snapshot() == before:
                break
        else:
            raise ClassUnsupported(self.tree)
    def run(self):
        self.infer_until_stable()
        for owner in self.classes.values():
            for value in owner.fields.values():
                if value.cell.root().tag is None and not value.written:
                    # No permitted operation can ever create this attribute.
                    # The getter always raises before its phantom result is used.
                    merge(value.cell, Cell("int"), owner.node)
        for value in self.records.values():
            value = value.root()
            if value.tag == "list" and value.args[0].root().tag is None:
                # A closed empty allocation has no observable element kind.
                # Any append, store, argument or return flow has already added
                # its element constraints before this default is selected.
                merge(value.args[0],Cell("int"),self.tree)
        # Defaulting previously uninhabited storage adds type facts. Directional
        # consumers must reach a new fixed point before result validation.
        self.infer_until_stable()
        for plan in self.plans[1:]:
            if plan.reachable and plan.result.root().tag is None:
                if all(isinstance(value.value, ast.Call) for value in ast.walk(plan.node)
                       if isinstance(value, ast.Return) and value.value is not None):
                    merge(plan.result, Cell("none"), plan.node)
                else:
                    raise ClassUnsupported(plan.node)
        self.final = True
        self.module.visible_definitions = set()
        self.block(self.module, self.tree.body, dict(self.global_symbols))
        for plan in self.plans[1:]:
            if plan.reachable:
                global_names={name:value for name,value in self.global_symbols.items() if name not in plan.declared}
                self.block(plan, plan.node.body, {**global_names, **plan.arguments})
        for owner in self.classes.values():
            if owner.used:
                initializer=owner.methods.get("__init__")
                if initializer is not None and shape(initializer.result)!="none":raise ClassUnsupported(initializer.node)
                for value in owner.fields.values():
                    self.storage(value.cell, owner.node, field_value=True)
        for plan in self.plans:
            if plan.reachable:
                self.storage(plan.result, plan.node)
                for value in plan.arguments.values():
                    self.storage(value, plan.node)
        return self

    def storage(self, cell, node, field_value=False):
        cell = cell.root()
        if cell.tag is None or cell.tag not in self.DATA:
            raise ClassUnsupported(node)
        if self.integer == "bigint" and cell.tag == "float":
            raise ClassUnsupported(node)
        if cell.tag == "object" and field_value:
            raise ClassUnsupported(node)
        if cell.tag == "list":
            item = cell.args[0].root()
            if not immutable_cell(item):raise ClassUnsupported(node)
            self.storage(item, node)
        if cell.tag == "union":
            for value in cell.args:self.storage(value,node,field_value=field_value)
        if cell.tag == "tuple":
            for value in cell.args:
                self.storage(value, node, field_value=field_value)

    def expression(self, plan, node, environment):
        if isinstance(node, ast.Constant):
            from .literal_semantics import Literal
            literal=Literal.from_ast(node)
            if literal is None:
                raise ClassUnsupported(node)
            return self.cell(plan, node, literal.kind)
        if isinstance(node, ast.Name):
            name = self.resolved_name(plan,node)
            if name in environment:
                value=environment[name]
                if (plan is self.module and name in CORE_BUILTINS and value.root().tag in self.INTRINSICS
                        and name not in getattr(environment,"definite",environment)):
                    raise ClassUnsupported(node)
                return self.remember(plan, node, value)
            if node.id == "__name__" and name not in plan.declared:
                return self.cell(plan, node, "str")
            if name in plan.declared:
                values = plan.locals.get(name, [])
                known = [value for value in values if value.root().tag is not None]
                if known:
                    result = known[0]
                    for value in known[1:]:
                        merge(result,value,node)
                    return self.remember(plan,node,result)
                if not self.final:
                    return self.cell(plan,node)
            raise ClassUnsupported(node)
        if isinstance(node, ast.List):
            result = self.cell(plan, node, "list", (Cell(),))
            for value in node.elts:
                self.contribute(result.root().args[0], self.expression(plan, value, environment), value)
            return result
        if isinstance(node, ast.Tuple):
            return self.cell(plan, node, "tuple", tuple(self.expression(plan, value, environment) for value in node.elts))
        if isinstance(node, ast.Attribute):
            receiver = self.expression(plan, node.value, environment).root()
            if receiver.tag is None and not self.final:
                return self.cell(plan, node)
            if receiver.tag == "object":
                owner = self.classes[receiver.args[0]]
                name = self.resolved_name(plan,node)
                return self.remember(plan, node, self.field(owner, name, node))
            intrinsic = {("sys","stdin"):"stdin", ("stdin","buffer"):"stdin_buffer",
                         ("stdin","readline"):"reader_text", ("stdin","read"):"read_text",
                         ("stdin_buffer","readline"):"reader_bytes", ("stdin_buffer","read"):"read_bytes"}.get((receiver.tag,node.attr))
            if intrinsic:
                return self.cell(plan, node, intrinsic)
            raise ClassUnsupported(node)
        if isinstance(node, ast.Subscript):
            if isinstance(node.slice, ast.Slice):
                raise ClassUnsupported(node)
            owner = self.expression(plan, node.value, environment).root()
            index = self.expression(plan, node.slice, environment).root()
            if index.tag not in {None,"int","bool","int_bool"}:
                raise ClassUnsupported(node.slice)
            if owner.tag == "list":
                return self.remember(plan, node, owner.args[0])
            if owner.tag == "tuple" and isinstance(node.slice, ast.Constant) and type(node.slice.value) is int:
                if not -len(owner.args) <= node.slice.value < len(owner.args):
                    raise ClassUnsupported(node)
                return self.remember(plan, node, owner.args[node.slice.value])
            if owner.tag in {"str","bytes"}:
                return self.cell(plan, node, "str" if owner.tag == "str" else "int")
            if owner.tag is None and not self.final:
                return self.cell(plan, node)
            raise ClassUnsupported(node)
        if isinstance(node, ast.BinOp):
            left = self.expression(plan, node.left, environment)
            right = self.expression(plan, node.right, environment)
            return self.binary(plan, node, node.op, left, right)
        if isinstance(node, ast.UnaryOp):
            value = self.expression(plan, node.operand, environment).root()
            if isinstance(node.op, ast.Not):
                return self.cell(plan, node, "bool")
            if value.tag in {"int","bool","int_bool","float"}:
                if value.tag == "float" and not isinstance(node.op,(ast.UAdd,ast.USub)):
                    raise ClassUnsupported(node)
                return self.cell(plan, node, "float" if value.tag == "float" else "int")
            if value.tag is None and not self.final:
                return self.cell(plan, node)
            raise ClassUnsupported(node)
        if isinstance(node, ast.Compare):
            self.expression(plan, node.left, environment)
            for value in node.comparators:
                self.expression(plan, value, environment)
            return self.cell(plan, node, "bool")
        if isinstance(node, ast.BoolOp):
            result = self.cell(plan, node)
            for value in node.values:
                self.contribute(result, self.expression(plan, value, environment), node)
            return result
        if isinstance(node, ast.IfExp):
            self.expression(plan, node.test, environment)
            result = self.cell(plan, node)
            self.contribute(result, self.expression(plan, node.body, environment), node)
            self.contribute(result, self.expression(plan, node.orelse, environment), node)
            return result
        if isinstance(node, ast.Call):
            return self.call(plan, node, environment)
        raise ClassUnsupported(node)

    def binary(self, plan, node, operator, left, right):
        a, b = left.root(), right.root()
        if a.tag is None or b.tag is None:
            if self.final:
                raise ClassUnsupported(node)
            return self.cell(plan, node)
        if isinstance(operator, ast.Add) and a.tag == b.tag == "list":
            merge(a.args[0], b.args[0], node)
            return self.cell(plan, node, "list", (a.args[0],))
        if isinstance(operator, ast.Mult) and (a.tag == "list" or b.tag == "list"):
            values, count = (a,b) if a.tag == "list" else (b,a)
            if count.tag not in {"int","bool","int_bool"}:
                raise ClassUnsupported(node)
            return self.cell(plan, node, "list", (values.args[0],))
        if a.tag == b.tag == "str" and isinstance(operator,ast.Add):
            return self.cell(plan, node, "str")
        if isinstance(operator,ast.Mult) and "str" in {a.tag,b.tag}:
            other = b if a.tag == "str" else a
            if other.tag not in {"int","bool","int_bool"}:
                raise ClassUnsupported(node)
            return self.cell(plan,node,"str")
        numeric = {"int","bool","int_bool","float"}
        if a.tag not in numeric or b.tag not in numeric:
            raise ClassUnsupported(node)
        if "float" in {a.tag,b.tag} or isinstance(operator,ast.Div):
            if self.integer == "bigint" or not isinstance(operator,(ast.Add,ast.Sub,ast.Mult,ast.Div,ast.FloorDiv,ast.Mod)):
                raise ClassUnsupported(node)
            return self.cell(plan,node,"float")
        if isinstance(operator,(ast.BitAnd,ast.BitOr,ast.BitXor)) and {a.tag,b.tag} <= {"bool","int_bool"}:
            return self.cell(plan,node,"bool" if a.tag == b.tag == "bool" else "int_bool")
        if not isinstance(operator,(ast.Add,ast.Sub,ast.Mult,ast.FloorDiv,ast.Mod,ast.Pow,ast.LShift,ast.RShift,ast.BitAnd,ast.BitOr,ast.BitXor)):
            raise ClassUnsupported(node)
        return self.cell(plan,node,"int")

    def bind_call(self, caller, node, callee, argument_cells, keyword_cells, environment):
        try:normalize_call(node)
        except CallBindingError:raise ClassUnsupported(node)from None
        names=(set(environment)|set(caller.visible_definitions or ()))if caller is self.module else caller.global_names
        if names is None:raise ClassUnsupported(node)
        if callee.global_names is None:callee.global_names=set(names)
        else:callee.global_names.update(names)
        callee.reachable = True
        visible = set(caller.visible_definitions or ())
        if callee.visible_definitions is None:
            callee.visible_definitions = visible
        else:
            callee.visible_definitions.intersection_update(visible)
        try:
            bound=callee.signature.bind(argument_cells,keyword_cells,callee.default_cells).by_name
        except CallBindingError:
            raise ClassUnsupported(node)from None
        for name, value in bound.items():
            self.contribute(callee.arguments[name], value, node)
        return self.remember(caller, node, callee.result)

    def call(self, plan, node, environment):
        function = node.func
        if (isinstance(function,ast.Name)and plan is self.module and function.id in CORE_BUILTINS
                and function.id in environment and environment[function.id].root().tag in self.INTRINSICS
                and function.id not in getattr(environment,"definite",environment)):
            raise ClassUnsupported(function)
        if (isinstance(function,ast.Name) and plan is not self.module
                and self.resolved_name(plan,function) in plan.declared and self.resolved_name(plan,function) not in environment):
            raise ClassUnsupported(node)
        if (isinstance(function,ast.Name) and function.id in self.BUILTINS
                and self.resolved_name(plan,function) not in environment
                and function.id not in self.classes and function.id not in self.functions
                and not isinstance(self.builtin_identity(plan,function,environment),BuiltinIdentity)):
            raise ClassUnsupported(function)
        if (isinstance(function,ast.Name) and self.builtin_identity(plan,function,environment)==BuiltinIdentity("map")
                and len(node.args) == 2 and not node.keywords and isinstance(node.args[0],ast.Name)
                and self.builtin_identity(plan,node.args[0],environment)==BuiltinIdentity("int")):
            words = self.expression(plan,node.args[1],environment)
            member = self.item(words,node).root()
            if member.tag not in {None,"str","bytes"}:
                raise ClassUnsupported(node)
            return self.cell(plan,node,"map_int",(words,))
        receiver = None
        if isinstance(function,ast.Attribute):
            receiver = self.expression(plan,function.value,environment).root()
        arguments = [self.expression(plan,value,environment) for value in node.args]
        keywords = [(value.arg,self.expression(plan,value.value,environment)) for value in node.keywords]
        if isinstance(function,ast.Name) and self.resolved_name(plan,function) not in environment:
            if function.id in self.classes:
                if function.id not in (plan.visible_definitions or ()):
                    raise ClassUnsupported(node)
                owner = self.classes[function.id]
                owner.used = True
                result = self.cell(plan,node,"object",(owner.node.name,))
                initializer = owner.methods.get("__init__")
                if initializer:
                    self.bind_call(plan,node,initializer,[result]+arguments,keywords,environment)
                    merge(initializer.result,Cell("none"),initializer.node)
                    return self.remember(plan,node,result)
                if arguments or keywords:
                    raise ClassUnsupported(node)
                return result
            if function.id in self.functions:
                if function.id not in (plan.visible_definitions or ()):
                    raise ClassUnsupported(node)
                return self.bind_call(plan,node,self.functions[function.id],arguments,keywords,environment)
            name = function.id
            if name == "print":
                if any(key not in {"sep","end","flush"} for key,_ in keywords):
                    raise ClassUnsupported(node)
                return self.cell(plan,node,"none")
            if name == "input" and not arguments and not keywords:
                return self.cell(plan,node,"str")
            if name in {"int","str","bool","float"} and len(arguments) <= 1 and not keywords:
                if name == "float" and self.integer == "bigint":
                    raise ClassUnsupported(node)
                return self.cell(plan,node,{"int":"int","str":"str","bool":"bool","float":"float"}[name])
            if name == "len" and len(arguments) == 1 and not keywords:
                return self.cell(plan,node,"int")
            if name in {"abs","id"} and len(arguments) == 1 and not keywords:
                return self.cell(plan,node,"int")
            if name == "range" and 1 <= len(arguments) <= 3 and not keywords:
                return self.cell(plan,node,"range")
            if name == "enumerate" and 1 <= len(arguments) <= 2 and not keywords:
                index = arguments[1] if len(arguments) == 2 else Cell("int")
                return self.cell(plan,node,"enumerate",(arguments[0],index))
            if name == "map" and len(node.args) == 2 and not keywords:
                raise ClassUnsupported(node)
            if name == "list" and len(arguments) <= 1 and not keywords:
                result = self.cell(plan,node,"list",(Cell(),))
                if arguments:
                    merge(result.root().args[0],self.item(arguments[0],node),node)
                return result
            if name == "sum" and 1 <= len(arguments) <= 2 and not keywords:
                item = self.item(arguments[0],node).root()
                if item.tag not in {None,"int","bool","int_bool"}:
                    raise ClassUnsupported(node)
                return self.cell(plan,node,"int")
            if name in {"min","max"} and arguments and not keywords:
                result = self.cell(plan,node)
                for value in arguments if len(arguments)>1 else [self.item(arguments[0],node)]:
                    merge(result,value,node)
                return result
        if isinstance(function,ast.Name) and self.resolved_name(plan,function) in environment:
            callable_ = environment[self.resolved_name(plan,function)].root()
            if callable_.tag in {"reader_text","reader_bytes","read_text","read_bytes"} and not arguments and not keywords:
                self.remember(plan,function,callable_)
                return self.cell(plan,node,"bytes" if callable_.tag in {"reader_bytes","read_bytes"} else "str")
        if receiver is not None:
            if receiver.tag == "object":
                owner = self.classes[receiver.args[0]]
                method = owner.methods.get(self.resolved_name(plan,function))
                if method is None:
                    raise ClassUnsupported(function)
                return self.bind_call(plan,node,method,[receiver]+arguments,keywords,environment)
            if receiver.tag == "list":
                from .native_sequence_plans import sequence_method
                method=sequence_method(shape(receiver),function.attr)
                if method is not None:
                    try:
                        defaults={name:Cell("none"if value is None else"bool"if type(value)is bool else"int")
                                  for name,value in method.defaults}
                        bound=method.signature.bind([receiver]+arguments,keywords,defaults).by_name
                    except CallBindingError:raise ClassUnsupported(node)from None
                    self.sequence_calls[(plan.index,id(node))]=method
                    item=receiver.args[0]
                    if method.name=="append":self.contribute(item,bound["value"],node)
                    elif method.name=="extend":self.contribute(item,self.item(bound["iterable"],node),node)
                    elif method.name=="sort"and bound["key"].root().tag not in {None,"none"}:
                        raise ClassUnsupported(node)
                    if method.result=="copy":return self.cell(plan,node,"list",(item,))
                    if method.result=="element":return self.remember(plan,node,item)
                    return self.cell(plan,node,method.result)
            if receiver.tag in {"str","bytes"} and function.attr == "split" and not arguments and not keywords:
                return self.cell(plan,node,"list",(Cell(receiver.tag),))
            if receiver.tag in {"str","bytes"} and function.attr == "strip" and not arguments and not keywords:
                return self.cell(plan,node,receiver.tag)
            if receiver.tag == "str" and function.attr == "join" and len(arguments) == 1 and not keywords:
                merge(self.item(arguments[0],node),Cell("str"),node)
                return self.cell(plan,node,"str")
            if receiver.tag in {"int","bool","int_bool"} and function.attr in {"bit_length","bit_count"} and not arguments and not keywords:
                return self.cell(plan,node,"int")
            if receiver.tag == "sys" and function.attr in {"setrecursionlimit","getrecursionlimit"} and not keywords:
                if len(arguments) != (1 if function.attr == "setrecursionlimit" else 0):
                    raise ClassUnsupported(node)
                return self.cell(plan,node,"none" if arguments else "int")
            intrinsic = {("stdin","readline"):"str", ("stdin","read"):"str",
                         ("stdin_buffer","readline"):"bytes", ("stdin_buffer","read"):"bytes"}.get((receiver.tag,function.attr))
            if intrinsic and not arguments and not keywords:
                return self.cell(plan,node,intrinsic)
            if receiver.tag is None and not self.final:
                return self.cell(plan,node)
        raise ClassUnsupported(node)

    def item(self, value, node):
        value = value.root()
        if value.tag == "list":
            return value.args[0]
        if value.tag == "tuple":
            result = Cell()
            for item in value.args:
                self.contribute(result,item,node)
            return result
        if value.tag == "range":
            return Cell("int")
        if value.tag == "enumerate":
            return Cell("tuple",(Cell("int"),self.item(value.args[0],node)))
        if value.tag == "map_int":
            return Cell("int")
        if value.tag in {"str","bytes"}:
            return Cell("str" if value.tag == "str" else "int")
        if value.tag is None and not self.final:
            return Cell()
        raise ClassUnsupported(node)

    def target(self, plan, node, value, environment):
        if isinstance(node,ast.Name):
            name = self.resolved_name(plan,node)
            if value.root().tag in {"map_int","enumerate"}:
                raise ClassUnsupported(node)
            if plan is self.module and name in self.global_symbols:
                raise ClassUnsupported(node)
            environment[name] = value
            environment.definite.add(name)
            self.canonical_local(plan,name,value)
            self.remember(plan,node,value)
            return
        if isinstance(node,(ast.Tuple,ast.List)):
            source = value.root()
            if source.tag == "tuple":
                if len(source.args) != len(node.elts):
                    raise ClassUnsupported(node)
                members = source.args
            else:
                members = [self.item(source,node)]*len(node.elts)
            for target, member in zip(node.elts,members):
                self.target(plan,target,member,environment)
            return
        if isinstance(node,ast.Attribute):
            owner = self.expression(plan,node.value,environment).root()
            if owner.tag == "object":
                field_ = self.field(self.classes[owner.args[0]],self.resolved_name(plan,node),node,writing=True)
                self.contribute(field_,value,node)
                self.remember(plan,node,field_)
                return
            if owner.tag is None and not self.final:
                return
        if isinstance(node,ast.Subscript) and not isinstance(node.slice,ast.Slice):
            owner = self.expression(plan,node.value,environment).root()
            self.expression(plan,node.slice,environment)
            if owner.tag == "list":
                self.contribute(owner.args[0],value,node)
                self.remember(plan,node,owner.args[0])
                return
            if owner.tag is None and not self.final:
                return
        raise ClassUnsupported(node)

    def join(self, left, right, node):
        if left is None:
            return right
        if right is None:
            return left
        result = Environment(left,definite=left.definite&right.definite)
        for name,value in right.items():
            if name in result:
                result[name] = merge(result[name],value,node)
            else:
                result[name] = value
        return result

    def block(self, plan, statements, environment):
        environment = Environment(environment)
        for node in statements:
            if environment is None:
                break
            if isinstance(node,(ast.ClassDef,ast.FunctionDef)):
                if plan is not self.module:
                    raise ClassUnsupported(node)
                expected = self.classes.get(node.name) if isinstance(node,ast.ClassDef) else self.functions.get(node.name)
                if expected is None or expected.node is not node:
                    raise ClassUnsupported(node)
                plan.visible_definitions.add(node.name)
                continue
            if isinstance(node,ast.Import):
                if plan is not self.module:
                    raise ClassUnsupported(node)
                continue
            if isinstance(node,ast.Pass):
                continue
            if isinstance(node,ast.Expr):
                self.expression(plan,node.value,environment)
            elif isinstance(node,ast.Assign):
                if (isinstance(node.value,ast.Call) and isinstance(node.value.func,ast.Name)
                        and self.builtin_identity(plan,node.value.func,environment)==BuiltinIdentity("map")
                        and len(node.value.args)==2 and not node.value.keywords
                        and isinstance(node.value.args[0],ast.Name) and node.value.args[0].id == "int" and "int" not in environment):
                    words = self.expression(plan,node.value.args[1],environment)
                    member = self.item(words,node.value).root()
                    if member.tag not in {"str","bytes",None}:
                        raise ClassUnsupported(node.value)
                    value = self.cell(plan,node.value,"map_int",(words,))
                else:
                    value = self.expression(plan,node.value,environment)
                for target in node.targets:
                    self.target(plan,target,value,environment)
            elif isinstance(node,ast.AugAssign):
                left = self.expression(plan,node.target,environment)
                self.augmented[(plan.index,id(node))] = left
                right = self.expression(plan,node.value,environment)
                value = self.binary(plan,node,node.op,left,right)
                self.target(plan,node.target,value,environment)
            elif isinstance(node,ast.If):
                self.expression(plan,node.test,environment)
                environment = self.join(self.block(plan,node.body,environment),self.block(plan,node.orelse,environment),node)
            elif isinstance(node,(ast.For,ast.While)):
                if node.orelse:
                    raise ClassUnsupported(node)
                start = Environment(environment)
                if isinstance(node,ast.For):
                    value = self.expression(plan,node.iter,environment)
                    self.target(plan,node.target,self.item(value,node.iter),environment)
                else:
                    self.expression(plan,node.test,environment)
                self.loop_depth += 1
                self.loop_edges.append([])
                body = self.block(plan,node.body,environment)
                edges = self.loop_edges.pop()
                self.loop_depth -= 1
                environment = self.join(start,body,node)
                for edge in edges:
                    environment = self.join(environment,edge,node)
                if node.orelse:
                    environment = self.block(plan,node.orelse,environment)
            elif isinstance(node,ast.Return):
                if plan is self.module:
                    raise ClassUnsupported(node)
                value = Cell("none") if node.value is None else self.expression(plan,node.value,environment)
                self.contribute(plan.result,value,node)
                environment = None
            elif isinstance(node,(ast.Break,ast.Continue)):
                if not self.loop_depth:
                    raise ClassUnsupported(node)
                self.loop_edges[-1].append(Environment(environment))
                environment = None
            else:
                raise ClassUnsupported(node)
        return environment


# Function and method emitters consume the same immutable typed expression.
Expression = _Expression



class Emitter:
    def __init__(self, model, plan):
        self.model, self.plan = model, plan
        self.counter = 0
        self.loops = []
        self.slots = {}
        self.reference_slots = {}
        if model.integer == "bigint":
            from .native_bigint import BigIntGenerator
            self.numeric = BigIntGenerator(function=SimpleNamespace(node=SimpleNamespace(name=plan.scope)))
        else:
            from .native_scalar import ScalarGenerator
            self.numeric = ScalarGenerator(64 if model.integer == "i64" else 128,
                                           function=SimpleNamespace(node=SimpleNamespace(name=plan.scope)))
        self.numeric.string_mode=model.string_mode
        for name, values in plan.locals.items():
            for value in values:
                kind = shape(value)
                if domain(kind) in model.DATA:self.slot(name,kind)
                elif domain(kind) in model.INTRINSICS:self.reference_slot(name,kind)

    def fresh(self):
        self.counter += 1
        return f"class_temp_{self.counter}"

    def kind(self, node):
        try:
            result = shape(self.model.records[(self.plan.index,id(node))])
        except KeyError:
            raise ClassUnsupported(node) from None
        if domain(result) is None:
            raise ClassUnsupported(node)
        return result

    def rust_type(self, kind):
        def leaf(value, recurse):
            if isinstance(value,InstanceType):return f"ClassHandle_{self.model.classes[value.name].index}"
            if isinstance(value,ListType):return f"ClassList<{recurse(value.element)}>"
            if value=="range":return "ClassRange"
            if isinstance(value,StreamType)or isinstance(value,str)and value in self.model.INTRINSICS:
                raise ClassUnsupported(self.plan.node)
            return None
        return render_type(kind,leaf)

    def slot(self, name, kind):
        key = name,kind
        if key not in self.slots:
            self.slots[key] = f"class_local_{len(self.slots)}"
        return self.slots[key]

    def reference_slot(self,name,kind):
        key=name,kind
        if key not in self.reference_slots:self.reference_slots[key]=f"class_ref_{len(self.reference_slots)}"
        return self.reference_slots[key]

    def reference_read(self,name,kind,node):
        if name in self.model.global_symbols and name not in self.plan.declared:return Expression("()",kind)
        slot=self.reference_slot(name,kind)
        error="NameError"if self.plan is self.model.module else"UnboundLocalError"
        message=(f"name '{name}' is not defined"if error=="NameError"else
                 f"cannot access local variable '{name}' where it is not associated with a value")
        result=f"if {slot}{{Ok(())}}else{{Err({_string(error+': '+message)}.to_owned())}}"
        return Expression(self.at(result,node),kind)

    def at(self, result, node):
        return f"native_at({result},{node.lineno},{_string(self.plan.scope)})?"

    def unsupported(self, node):
        raise ClassUnsupported(node)

    def coerce(self, value, kind, node):
        if value.kind == kind:return value.code
        if union_kind(value.kind):
            return project(value.kind,value.code,
                lambda source,code:self.coerce(Expression(f"({code}).clone()",source),kind,node))
        if union_kind(kind):
            choices=alternatives(kind)
            chosen=value.kind if value.kind in choices else next((option for option in choices
                if option=="int_bool"and value.kind in {"int","bool"}
                or isinstance(option,TupleType)and isinstance(value.kind,TupleType)
                    and len(option.fields)==len(value.kind.fields)),None)
            if chosen is None:raise ClassUnsupported(node)
            return construct(kind,chosen,self.coerce(value,chosen,node))
        if kind == "int_bool"and value.kind in {"int","bool"}:
            return f"NativeScalar::{'Int' if value.kind == 'int' else 'Bool'}({value.code})"
        if kind == "int"and value.kind in {"bool","int_bool"}:return self.number(value)
        if isinstance(kind,TupleType)and isinstance(value.kind,TupleType)and len(kind.fields)==len(value.kind.fields):
            temporary=self.fresh()
            values=[self.coerce(Expression(f"{temporary}.{i}.clone()",old),new,node)
                    for i,(old,new)in enumerate(zip(value.kind.fields,kind.fields))]
            return f"{{let {temporary}={value.code};"+tuple_code(values)+"}"
        raise ClassUnsupported(node)

    def encoded(self, code, raw_kind, wanted, node, constant=None):
        return Expression(self.coerce(Expression(code,raw_kind,constant),wanted,node),wanted,constant)

    def capture(self, value):
        name = self.fresh()
        return f"let {name}={value.code};",Expression(name,value.kind,value.constant)

    def scalar(self, value):
        return value

    def number(self, value):
        return self.numeric.number(self.scalar(value))

    def literal(self, value):
        return self.numeric.literal(value)

    def truth(self, value):
        if union_kind(value.kind):return project(value.kind,value.code,
            lambda kind,code:self.truth(Expression(code,kind)))
        tag = domain(value.kind)
        if tag in {"int","bool","int_bool"}:
            return self.numeric.truth(self.scalar(value))
        if tag in {"str","bytes"}:
            return f"!({value.code}).is_empty()"
        if tag == "float":
            return f"({value.code})!=0.0"
        if tag == "list":
            return f"!({value.code}).borrow().is_empty()"
        if tag == "none":
            return "false"
        if tag == "object":
            owner=self.model.classes[value.kind.name]
            if owner.node.bases or any(name in owner.methods for name in {"__bool__","__len__"}):
                raise ClassUnsupported(owner.node)
            return "true"
        if tag == "tuple":
            return str(bool(value.kind.fields)).lower()
        raise ClassUnsupported(self.plan.node)

    def show(self, value, node, representation=False):
        if union_kind(value.kind):return project(value.kind,value.code,
            lambda kind,code:self.show(Expression(code,kind),node,representation))
        if isinstance(value.kind,ListType):
            item=self.fresh()
            rendered=self.show(Expression(f"(*{item}).clone()",value.kind.element),node,True)
            return f'format!("[{{}}]",({value.code}).borrow().iter().map(|{item}|{rendered}).collect::<Vec<_>>().join(", "))'
        tag = domain(value.kind)
        if tag == "tuple":
            fields = [self.show(Expression(f"{value.code}.{i}.clone()",kind),node,True)
                      for i,kind in enumerate(value.kind.fields)]
            return "class_tuple_text(&[" + ",".join(fields) + "])"
        if tag in {"int","bool","int_bool","str","bytes","none","object","list","float"}:
            return f"ClassDisplay::class_{'repr' if representation else 'str'}(&({value.code}))"
        raise ClassUnsupported(node)

    def literal_value(self,value,wanted,node):
        from .literal_semantics import Literal
        literal=Literal.from_value(value)
        if literal is None:raise ClassUnsupported(node)
        constant=(self.numeric.normalize(value)if literal.kind=="int"else value if literal.kind=="bool"else None)
        code=literal.rust_atom(self.literal,_string)
        return self.encoded(code,literal.kind,wanted,node,constant)

    def captured_defaults(self,callee):
        return {name:self.literal_value(value,shape(callee.default_cells[name]),callee.defaults[name])
                for name,value in callee.default_literals.items()}

    def expression(self, node):
        wanted = self.kind(node)
        if isinstance(node,ast.Constant):
            return self.literal_value(node.value,wanted,node)
        if isinstance(node,ast.Name):
            name = self.model.resolved_name(self.plan,node)
            if domain(wanted) in self.model.INTRINSICS:
                return self.reference_read(name,wanted,node)
            if node.id == "__name__" and name not in self.plan.locals:
                return Expression('NativeText::from("__main__")','str')
            slot = self.slot(name,wanted)
            kind = "NameError" if self.plan is self.model.module else "UnboundLocalError"
            message = (f"name '{name}' is not defined" if kind == "NameError" else
                       f"cannot access local variable '{name}' where it is not associated with a value")
            result = f"{slot}.clone().ok_or_else(||{_string(kind+': '+message)}.to_owned())"
            return Expression(self.at(result,node),wanted)
        if isinstance(node,ast.Tuple):
            raw=shape(self.model.constructors[(self.plan.index,id(node))])
            values=[self.coerce(self.expression(value),kind,value)for value,kind in zip(node.elts,raw.fields)]
            return self.encoded(tuple_code(values),raw,wanted,node)
        if isinstance(node,ast.List):
            values = [self.coerce(self.expression(value),wanted.element,value) for value in node.elts]
            return Expression("class_list(vec!["+",".join(values)+"])",wanted)
        if isinstance(node,ast.Attribute):
            if domain(wanted) in self.model.INTRINSICS:
                receiver=self.expression(node.value)
                return Expression("{let _="+receiver.code+";()}",wanted)
            receiver = self.expression(node.value)
            if domain(receiver.kind) != "object":
                raise ClassUnsupported(node)
            owner = self.model.classes[receiver.kind.name]
            index = list(owner.fields).index(self.model.resolved_name(self.plan,node))
            return Expression(self.at(f"class_get_{owner.index}_{index}(&({receiver.code}))",node),wanted)
        if isinstance(node,ast.Subscript):
            setup,owner = self.capture(self.expression(node.value))
            index_setup,index = self.capture(self.expression(node.slice))
            tag = domain(owner.kind)
            if tag == "list":
                code = self.at(f"class_list_get(&{owner.code},&({self.number(index)}))",node)
            elif tag == "tuple":
                position = node.slice.value % (len(owner.kind.fields))
                code = f"{owner.code}.{position}.clone()"
            elif tag == "str":
                code = self.at(f"class_string_get(&{owner.code},&({self.number(index)}))",node)
            elif tag == "bytes":
                offset = self.at(f"class_index(&({self.number(index)}),{owner.code}.len())",node)
                code = f"class_from_usize({owner.code}[{offset}] as usize)"
            else:
                raise ClassUnsupported(node)
            return Expression(f"{{{setup}{index_setup}{code}}}",wanted)
        if isinstance(node,ast.BinOp):
            setup,left = self.capture(self.expression(node.left))
            more,right = self.capture(self.expression(node.right))
            result = self.binary(node.op,left,right,node,wanted)
            return Expression(f"{{{setup}{more}{result.code}}}",wanted,result.constant)
        if isinstance(node,ast.UnaryOp):
            setup,value = self.capture(self.expression(node.operand))
            if isinstance(node.op,ast.Not):
                raw = Expression(f"!({self.truth(value)})",'bool')
            elif value.kind == 'float':
                raw = Expression(("-"if isinstance(node.op,ast.USub)else"")+value.code,'float')
            else:
                number = self.number(value)
                if isinstance(node.op,ast.UAdd):
                    code = number
                elif isinstance(node.op,ast.USub):
                    code = f"({number}).neg()"if self.model.integer=="bigint"else f"({number}).wrapping_neg()"
                else:
                    code = f"({number}).invert()"if self.model.integer=="bigint"else f"!({number})"
                constant = None
                if value.constant is not None:
                    constant = self.numeric.normalize(-int(value.constant) if isinstance(node.op,ast.USub) else
                                                      ~int(value.constant) if isinstance(node.op,ast.Invert) else int(value.constant))
                raw = Expression(code,'int',constant)
            return Expression(f"{{{setup}{self.coerce(raw,wanted,node)}}}",wanted,raw.constant)
        if isinstance(node,ast.IfExp):
            setup,test = self.capture(self.expression(node.test))
            yes = self.coerce(self.expression(node.body),wanted,node.body)
            no = self.coerce(self.expression(node.orelse),wanted,node.orelse)
            return Expression("{"+setup+"if "+self.truth(test)+"{"+yes+"}else{"+no+"}}",wanted)
        if isinstance(node,ast.BoolOp):
            def combine(values):
                current = self.expression(values[0])
                if len(values)==1:
                    return self.coerce(current,wanted,node)
                setup,value = self.capture(current)
                retained = self.coerce(value,wanted,node)
                rest = combine(values[1:])
                yes,no = (rest,retained)if isinstance(node.op,ast.And)else(retained,rest)
                return "{"+setup+"if "+self.truth(value)+"{"+yes+"}else{"+no+"}}"
            return Expression(combine(node.values),wanted)
        if isinstance(node,ast.Compare):
            values = [node.left]+node.comparators
            first_setup,first = self.capture(self.expression(values[0]))
            def tail(index,left):
                if index==len(node.ops):
                    return "true"
                setup,right = self.capture(self.expression(values[index+1]))
                test = self.comparison(node.ops[index],left,right,node)
                return f"{{{setup}({test})&&({tail(index+1,right)})}}"
            return Expression(f"{{{first_setup}{tail(0,first)}}}",wanted)
        if isinstance(node,ast.Call):
            return self.call(node)
        raise ClassUnsupported(node)

    def binary(self, operator, left, right, node, wanted):
        a,b = domain(left.kind),domain(right.kind)
        if a==b=="list" and isinstance(operator,ast.Add):
            return Expression(f"class_list_concat(&{left.code},&{right.code})",wanted)
        if "list" in {a,b} and isinstance(operator,ast.Mult):
            values,count = (left,right)if a=="list"else(right,left)
            return Expression(self.at(f"class_list_repeat(&{values.code},&({self.number(count)}))",node),wanted)
        if a==b=="str" and isinstance(operator,ast.Add):
            return Expression(self.at(f"class_string_add({left.code},&{right.code})",node),wanted)
        if "str" in {a,b} and isinstance(operator,ast.Mult):
            value,count = (left,right)if a=="str"else(right,left)
            return Expression("NativeText::from("+self.at(f"class_string_repeat(&{value.code},&({self.number(count)}))",node)+")",wanted)
        result = self.numeric.binary(operator,self.scalar(left),self.scalar(right),node)
        raw = result.kind
        return self.encoded(result.code,raw,wanted,node,result.constant)

    def comparison(self, operator, left, right, node):
        if union_kind(left.kind):return project(left.kind,left.code,
            lambda kind,code:self.comparison(operator,Expression(f"({code}).clone()",kind),right,node))
        if union_kind(right.kind):return project(right.kind,right.code,
            lambda kind,code:self.comparison(operator,left,Expression(f"({code}).clone()",kind),node))
        a,b = domain(left.kind),domain(right.kind)
        if isinstance(operator,(ast.Is,ast.IsNot)):
            if a==b and a in {"object","list"}:
                code = (f"Rc::ptr_eq(&{left.code},&{right.code})"if left.kind==right.kind else"false")
            elif a==b=="none":
                code = "true"
            elif a==b=="bool":
                code = f"{left.code}=={right.code}"
            elif "none" in {a,b} or a!=b and not {a,b}<={"int","bool","int_bool"}:
                code = "false"
            elif {a,b}=={"int_bool","bool"}:
                scalar,boolean = (left,right)if a=="int_bool"else(right,left)
                code = f"matches!(&{scalar.code},NativeScalar::Bool(value)if *value=={boolean.code})"
            else:
                raise ClassUnsupported(node)
            return f"!({code})"if isinstance(operator,ast.IsNot)else code
        if not isinstance(operator,(ast.In,ast.NotIn))and(isinstance(left.kind,TupleType)or isinstance(right.kind,TupleType)):
            from .native_tuples import tuple_compare,_scalar
            if not _scalar(left.kind)or not _scalar(right.kind):raise ClassUnsupported(node)
            return tuple_compare(self,left,right,operator,node)
        if isinstance(operator,(ast.Eq,ast.NotEq)) and (a=="none"or b=="none"):
            code = str(a==b).lower()
            return f"!({code})"if isinstance(operator,ast.NotEq)else code
        if a==b=="object"and isinstance(operator,(ast.Eq,ast.NotEq)):
            code = f"Rc::ptr_eq(&{left.code},&{right.code})"if left.kind==right.kind else"false"
            return f"!({code})"if isinstance(operator,ast.NotEq)else code
        if a==b=="list"and isinstance(operator,(ast.Eq,ast.NotEq)):
            if has_float_payload(left.kind)or has_float_payload(right.kind):
                raise ClassUnsupported(node)
            if left.kind==right.kind:
                a_item,b_item=self.fresh(),self.fresh()
                test=self.comparison(ast.Eq(),Expression(f"{a_item}.clone()",left.kind.element),
                                     Expression(f"{b_item}.clone()",right.kind.element),node)
                code=(f"({left.code}).borrow().len()==({right.code}).borrow().len()&&"
                      f"({left.code}).borrow().iter().zip(({right.code}).borrow().iter()).all(|({a_item},{b_item})|{test})")
                return f"!({code})"if isinstance(operator,ast.NotEq)else code
            raise ClassUnsupported(node)
        if isinstance(operator,(ast.In,ast.NotIn))and b=="list":
            if has_float_payload(right.kind.element):
                raise ClassUnsupported(node)
            item = Expression("class_item.clone()",right.kind.element)
            test = self.comparison(ast.Eq(),left,item,node)
            code = f"{right.code}.borrow().iter().any(|class_item|{test})"
            return f"!({code})"if isinstance(operator,ast.NotIn)else code
        if a==b=="str"and isinstance(operator,(ast.In,ast.NotIn)):
            code=f"{right.code}.contains(&{left.code})"
            return f"!({code})"if isinstance(operator,ast.NotIn)else code
        numeric={"int","bool","int_bool"}
        symbols={ast.Eq:"==",ast.NotEq:"!=",ast.Lt:"<",ast.LtE:"<=",ast.Gt:">",ast.GtE:">="}
        if a in numeric and b in numeric and type(operator)in symbols:
            return f"({self.number(left)}){symbols[type(operator)]}({self.number(right)})"
        if a==b and a in {"str","bytes"}and type(operator)in symbols:
            return f"{left.code}{symbols[type(operator)]}{right.code}"
        if self.model.integer!="bigint"and a in numeric|{"float"}and b in numeric|{"float"}:
            temporary=SimpleNamespace(ops=[operator])
            return self.numeric.compare(temporary,[self.scalar(left),self.scalar(right)]).code
        if isinstance(operator,(ast.Eq,ast.NotEq))and a!=b:
            return str(isinstance(operator,ast.NotEq)).lower()
        raise ClassUnsupported(node)

    def function_name(self, plan):
        return f"class_function_{plan.index}"

    def call_user(self, node, callee, receiver=None, constructor=None):
        setup,arguments = [],[]
        if receiver is not None:
            before,receiver = self.capture(receiver)
            setup.append(before)
            arguments.append(receiver)
        try:call_arguments=normalize_call(node)
        except CallBindingError:raise ClassUnsupported(node)from None
        if callee is None:values=[]
        else:
            signature=callee.signature.without_receiver()if constructor is not None else callee.signature
            default_emitter=Emitter(self.model,callee)
            def argument_value(expression,parameter):
                before,value=self.capture(self.expression(expression))
                setup.append(before)
                return value
            try:
                call_plan=signature.plan(call_arguments,implicit_count=len(arguments))
                bound=call_plan.capture(argument_value,implicit=arguments,defaults=default_emitter.captured_defaults(callee))
            except CallBindingError:raise ClassUnsupported(node)from None
            values=[self.coerce(value,shape(callee.arguments[name]),node)for name,value in zip(bound.parameters,bound.values)]
        name = (f"class_construct_{constructor.index}"if constructor is not None else self.function_name(callee))
        # Constructor futures receive only explicit Python arguments. Their
        # internal __init__ future shares this logical call-stack entry.
        future = name+"(class_scope.clone()"+(" ,"+",".join(values)if values else"")+")"
        call = f"class_call(class_scope.clone(),{future},{node.lineno},{_string(self.plan.scope)}).await?"
        return Expression("{"+"\n".join(setup)+call+"}",self.kind(node))

    def parse_words(self, node, count=None):
        words = self.expression(node.args[1])
        before,words = self.capture(words)
        if domain(words.kind) != "list":
            raise ClassUnsupported(node)
        item = words.kind.element
        if item == 'str':
            parser = "|value:&NativeText|native_parse_integer(value)"
        elif item == 'bytes':
            parser = "|value:&Vec<u8>|class_parse_bytes(value)"
        else:
            raise ClassUnsupported(node)
        limit = "None"if count is None else f"Some({count})"
        call = self.at(f"class_parse_words(&{words.code},{limit},{parser})",node)
        return f"{{{before}{call}}}"

    def sequence_call(self,node,method):
        from .native_sequence_storage import capture_shared
        from .native_sequence_methods import lower
        emitter=self
        class Adapter:
            bits=emitter.numeric.bits
            temporary=emitter.fresh
            number=emitter.number
            truth=emitter.truth
            at=emitter.at
            def coerce(self,value,kind):return emitter.coerce(value,kind,node)
        adapter=Adapter()
        storage=capture_shared(adapter,self.expression(node.func.value))
        lines=list(storage.setup)
        bound={}
        try:call=method.signature.plan(normalize_call(node),implicit_count=1)
        except CallBindingError:raise ClassUnsupported(node)from None
        for argument,name in zip(call.arguments.evaluation_order,call.argument_parameters):
            before,value=self.capture(self.expression(argument.expression))
            lines.append(before)
            bound[name]=value
        if method.name=="sort"and "key"in bound and bound["key"].kind!="none":raise ClassUnsupported(node)
        result=lower(adapter,storage,method,bound,node,{},sort_key=None)
        temporary=self.fresh()
        return self.encoded("{"+"".join(lines)+f"let {temporary}={result.code};{temporary}"+"}",result.kind,self.kind(node),node)

    def call(self, node):
        method=self.model.sequence_calls.get((self.plan.index,id(node)))
        if method is not None:return self.sequence_call(node,method)
        function = node.func
        wanted = self.kind(node)
        if isinstance(function,ast.Name) and function.id in self.model.classes:
            owner = self.model.classes[function.id]
            return self.call_user(node,owner.methods.get("__init__"),constructor=owner)
        if isinstance(function,ast.Name) and function.id in self.model.functions:
            return self.call_user(node,self.model.functions[function.id])
        if isinstance(function,ast.Attribute):
            receiver = self.expression(function.value)
            if domain(receiver.kind) == "object":
                owner = self.model.classes[receiver.kind.name]
                method = owner.methods[self.model.resolved_name(self.plan,function)]
                return self.call_user(node,method,receiver)
        else:
            receiver = None
        if isinstance(function,ast.Name) and function.id == "map":
            raise ClassUnsupported(node)
        if (isinstance(function,ast.Name) and function.id == "list" and len(node.args)==1
                and domain(self.kind(node.args[0])) == "map_int"):
            values = self.parse_words(node.args[0])
            if wanted.element == 'int_bool':
                values = f"({values}).into_iter().map(NativeScalar::Int).collect::<Vec<_>>()"
            elif wanted.element != 'int':
                raise ClassUnsupported(node)
            return Expression(f"class_list({values})",wanted)
        setup,arguments = [],[]
        alias=self.model.records.get((self.plan.index,id(function)))
        if isinstance(function,ast.Name)and alias is not None and alias.root().tag in self.model.INTRINSICS:
            before,ignored=self.capture(self.expression(function))
            setup.append(before)
        if receiver is not None:
            before,receiver = self.capture(receiver)
            setup.append(before)
        for value in node.args:
            before,value = self.capture(self.expression(value))
            setup.append(before)
            arguments.append(value)
        keywords = {}
        for keyword in node.keywords:
            before,value = self.capture(self.expression(keyword.value))
            setup.append(before)
            keywords[keyword.arg] = value
        name = function.id if isinstance(function,ast.Name) else None
        alias_kind = self.model.records.get((self.plan.index,id(function)))
        if alias_kind is not None and alias_kind.root().tag in {"reader_text","reader_bytes","read_text","read_bytes"}:
            name = alias_kind.root().tag
        code = None
        raw_kind=shape(self.model.constructors[(self.plan.index,id(node))])if(self.plan.index,id(node))in self.model.constructors else wanted
        if name in {"input","reader_text","reader_bytes","read_text","read_bytes"}:
            if name in {"reader_bytes","read_bytes"}:
                code = self.at(f"class_read_bytes(&class_scope,{str(name=='reader_bytes').lower()})",node)
            else:
                code = self.at(f"class_read_text(&class_scope,{str(name!='read_text').lower()},{str(name=='input').lower()})",node)
        elif name == "print":
            sep = keywords.get("sep",Expression('" ".to_owned()','str'))
            end = keywords.get("end",Expression('"\\n".to_owned()','str'))
            if sep.kind == 'none':
                sep = Expression('" ".to_owned()','str')
            if end.kind == 'none':
                end = Expression('"\\n".to_owned()','str')
            if sep.kind != 'str' or end.kind != 'str':
                raise ClassUnsupported(node)
            pieces=[]
            for i,value in enumerate(arguments):
                if i:
                    pieces.append(f"class_scope.io.borrow_mut().output.push_str(&{sep.code});")
                pieces.append(f"class_scope.io.borrow_mut().output.push_str(&({self.show(value,node)}));")
            pieces.append(f"class_scope.io.borrow_mut().output.push_str(&{end.code});")
            if "flush"in keywords:
                flush = self.truth(keywords["flush"])
                call = self.at("native_flush_output(&mut class_scope.io.borrow_mut().output)",node)
                pieces.append(f"if {flush}{{{call};}}")
            code = "{"+"".join(pieces)+"()}"
        elif name == "len":
            value=arguments[0]
            if domain(value.kind)=="list":length=f"{value.code}.borrow().len()"
            elif domain(value.kind)=="str":
                length=f"{value.code}."+("len()"if self.model.string_mode=="ascii"else"codepoint_len()")
            elif domain(value.kind)=="bytes":length=f"{value.code}.len()"
            elif domain(value.kind)=="tuple":length=str(len(value.kind.fields))
            else:raise ClassUnsupported(node)
            code=f"class_from_usize({length})"
            raw_kind='int'
        elif name == "int":
            raw_kind='int'
            if not arguments:code=self.literal(0)
            elif domain(arguments[0].kind) in {"int","bool","int_bool"}:code=self.number(arguments[0])
            elif arguments[0].kind=='str':code=self.at(f"native_parse_integer(&{arguments[0].code})",node)
            elif arguments[0].kind=='bytes':code=self.at(f"class_parse_bytes(&{arguments[0].code})",node)
            elif arguments[0].kind=='float':code=self.at(f"native_float_integer({arguments[0].code})",node)
            else:raise ClassUnsupported(node)
        elif name == "str":
            code=('NativeText::new()'if not arguments else arguments[0].code+'.clone()'
                  if arguments[0].kind=="str"else self.show(arguments[0],node))
        elif name == "bool":
            code='false'if not arguments else self.truth(arguments[0])
            raw_kind='bool'
        elif name == "float":
            if not arguments:code="0.0_f64"
            elif domain(arguments[0].kind)in{"int","bool","int_bool"}:code=f"({self.number(arguments[0])}) as f64"
            elif arguments[0].kind=='float':code=arguments[0].code
            elif arguments[0].kind=='str':code=self.at(f"native_scalar_float(&{arguments[0].code})",node)
            else:raise ClassUnsupported(node)
        elif name == "abs":
            value=arguments[0]
            if domain(value.kind)in{"int","bool","int_bool"}:
                number=self.number(value)
                code=f"({number}).abs()"if self.model.integer=="bigint"else f"({number}).wrapping_abs()"
                raw_kind='int'
            else:raise ClassUnsupported(node)
        elif name == "id":
            if domain(arguments[0].kind)not in{"object","list"}:raise ClassUnsupported(node)
            code=f"class_from_usize(Rc::as_ptr(&{arguments[0].code}) as usize)"
            raw_kind='int'
        elif name == "range":
            values=[self.number(value)for value in arguments]
            if len(values)==1:values.insert(0,self.literal(0))
            if len(values)==2:values.append(self.literal(1))
            code=self.at("class_range("+",".join(values)+")",node)
        elif name == "list":
            if not arguments:code=f"class_list(Vec::<{self.rust_type(wanted.element)}>::new())"
            elif domain(arguments[0].kind)=="list":code=f"class_list({arguments[0].code}.borrow().clone())"
            elif domain(arguments[0].kind)=="range":
                values=f"{arguments[0].code}.iter()"
                if wanted.element=='int_bool':values+=".map(NativeScalar::Int)"
                code=f"class_list(({values}).collect::<Vec<_>>())"
            elif domain(arguments[0].kind)=="tuple":
                value=arguments[0]
                elements=[self.coerce(Expression(f"{value.code}.{i}.clone()",kind),wanted.element,node)for i,kind in enumerate(value.kind.fields)]
                code="class_list(vec!["+",".join(elements)+"])"
            else:raise ClassUnsupported(node)
        elif name in {"min","max","sum"}:
            accumulator=self.fresh();member=self.fresh()
            if name=="sum":
                start=arguments[1]if len(arguments)==2 else Expression(self.literal(0),'int',0)
                code=f"{{let mut {accumulator}={self.number(start)};"
                stream=arguments[0]
            elif len(arguments)>1:
                code=f"{{let mut {accumulator}={self.coerce(arguments[0],wanted,node)};"
                stream=None
                for candidate in arguments[1:]:
                    value=Expression(self.coerce(candidate,wanted,node),wanted)
                    comparison=self.comparison(ast.Lt()if name=="min"else ast.Gt(),value,Expression(accumulator,wanted),node)
                    code+=f"if {comparison}{{{accumulator}={value.code};}}"
                code+=accumulator+"}"
            else:
                code=f"{{let mut {accumulator}:Option<{self.rust_type(wanted)}>=None;"
                stream=arguments[0]
            if stream is not None:
                if domain(stream.kind)=="list":
                    iterator=f"{stream.code}.borrow().iter().cloned()";kind=stream.kind.element
                elif domain(stream.kind)=="range":
                    iterator=f"{stream.code}.iter()";kind='int'
                elif domain(stream.kind)=="tuple" and bool(stream.kind.fields):
                    kind=wanted if name!="sum"else'int'
                    values=[self.coerce(Expression(f"{stream.code}.{i}.clone()",old),kind,node)for i,old in enumerate(stream.kind.fields)]
                    iterator="["+",".join(values)+"].into_iter()"
                else:raise ClassUnsupported(node)
                if name=="sum":
                    value=self.numeric.binary(ast.Add(),_Expression(accumulator+".clone()","int"),self.scalar(Expression(member,kind)),node).code
                    action=f"{accumulator}={value};"
                    ending=accumulator
                else:
                    value=self.coerce(Expression(member,kind),wanted,node)
                    candidate=self.fresh();old=self.fresh()
                    comparison=self.comparison(ast.Lt()if name=="min"else ast.Gt(),Expression(candidate+".clone()",wanted),Expression(old+".clone()",wanted),node)
                    action=f"let {candidate}={value};let replace=match &{accumulator}{{Some({old})=>{comparison},None=>true}};if replace{{{accumulator}=Some({candidate});}}"
                    ending=self.at(f'{accumulator}.ok_or_else(||"ValueError: {name}() arg is an empty sequence".to_owned())',node)
                code+=f"for {member} in {iterator}{{{action}}}{ending}}}"
        elif receiver is not None:
            tag,method=domain(receiver.kind),function.attr
            if tag in {"str","bytes"}and method=="split":
                code=f"class_split_{'text'if tag=='str'else'bytes'}(&{receiver.code})"
            elif tag=="str"and method=="strip":code=f"{receiver.code}.trim_matches(native_space).to_owned()"
            elif tag=="bytes"and method=="strip":code=f"class_strip_bytes(&{receiver.code})"
            elif tag=="str"and method=="join":
                if arguments[0].kind!=ListType("str"):raise ClassUnsupported(node)
                code=f"{arguments[0].code}.borrow().join(&{receiver.code})"
            elif tag in{"int","bool","int_bool"}and method in{"bit_length","bit_count"}:
                value=self.number(receiver)
                if self.model.integer=="bigint":code=f"class_from_usize(({value}).{method}())"
                else:
                    count=f"NativeInt::BITS-({value}).unsigned_abs().leading_zeros()"if method=="bit_length"else f"({value}).unsigned_abs().count_ones()"
                    code=f"class_from_usize(({count})as usize)"
                raw_kind='int'
            elif tag=="sys"and method=="setrecursionlimit":
                limit=self.at(f"class_recursion_limit(&({self.number(arguments[0])}))",node)
                temporary=self.fresh()
                failure=self.at(f'Err::<(),String>(format!("RecursionError: cannot set the recursion limit to {{}} at the recursion depth {{}}: the limit is too low",{temporary},class_scope.control.borrow().depth))',node)
                code=f"{{let {temporary}={limit};if {temporary}<=class_scope.control.borrow().depth{{{failure};}}class_scope.control.borrow_mut().limit={temporary};()}}"
            elif tag=="sys"and method=="getrecursionlimit":code="class_from_usize(class_scope.control.borrow().limit)"
            elif tag in{"stdin","stdin_buffer"}and method in{"read","readline"}:
                if tag=="stdin":code=self.at(f"class_read_text(&class_scope,{str(method=='readline').lower()},false)",node)
                else:code=self.at(f"class_read_bytes(&class_scope,{str(method=='readline').lower()})",node)
            else:raise ClassUnsupported(node)
        if code is None:
            raise ClassUnsupported(node)
        if raw_kind=="str":code=f"NativeText::from({code})"
        result=self.encoded(code,raw_kind,wanted,node)
        return Expression("{"+"\n".join(setup)+"let class_value="+result.code+";class_value}",wanted,result.constant)

    def assign(self, target, value):
        if isinstance(target,ast.Name):
            kind = self.kind(target)
            name=self.model.resolved_name(self.plan,target)
            clearing="".join(f"{other}=None;"for(other_name,other_kind),other in self.slots.items()
                             if other_name==name and other_kind!=kind)
            clearing+="".join(f"{other}=false;"for(other_name,other_kind),other in self.reference_slots.items()
                              if other_name==name and other_kind!=kind)
            if domain(kind)in self.model.INTRINSICS:
                return clearing+f"{self.reference_slot(name,kind)}=true;"
            slot=self.slot(name,kind)
            return clearing+f"{slot}=Some({self.coerce(value,kind,target)});"
        if isinstance(target,(ast.Tuple,ast.List)):
            setup,source = self.capture(value)
            if domain(source.kind)=="tuple":
                pieces = [self.assign(node,Expression(f"{source.code}.{i}.clone()",kind))
                          for i,(node,kind)in enumerate(zip(target.elts,source.kind.fields))]
            elif domain(source.kind)=="list":
                unpack = self.fresh()
                setup += f"let {unpack}={self.at(f'class_unpack(&{source.code},{len(target.elts)})',target)};"
                pieces = [self.assign(node,Expression(f"{unpack}[{i}].clone()",source.kind.element))for i,node in enumerate(target.elts)]
            else:
                raise ClassUnsupported(target)
            return setup+"".join(pieces)
        setup,reference = self.reference(target)
        return setup+self.store_reference(reference,value,target)

    def reference(self, target):
        if isinstance(target,ast.Name):
            return "",("name",target)
        if isinstance(target,ast.Attribute):
            setup,owner = self.capture(self.expression(target.value))
            if domain(owner.kind)!="object":raise ClassUnsupported(target)
            plan=self.model.classes[owner.kind.name]
            name=self.model.resolved_name(self.plan,target)
            return setup,("field",owner,plan,list(plan.fields).index(name),shape(plan.fields[name].cell))
        if isinstance(target,ast.Subscript):
            setup,owner=self.capture(self.expression(target.value))
            more,index=self.capture(self.expression(target.slice))
            if domain(owner.kind)!="list":raise ClassUnsupported(target)
            return setup+more,("index",owner,index,owner.kind.element)
        raise ClassUnsupported(target)

    def load_reference(self, reference, node, kind=None):
        if reference[0]=="name":
            target=reference[1]
            kind=kind or self.kind(target)
            name=self.model.resolved_name(self.plan,target)
            slot=self.slot(name,kind)
            message=f"UnboundLocalError: cannot access local variable '{name}' where it is not associated with a value"
            if self.plan is self.model.module:message=f"NameError: name '{name}' is not defined"
            return Expression(self.at(f"{slot}.clone().ok_or_else(||{_string(message)}.to_owned())",node),kind)
        if reference[0]=="field":
            _,owner,plan,index,kind=reference
            return Expression(self.at(f"class_get_{plan.index}_{index}(&{owner.code})",node),kind)
        _,owner,index,kind=reference
        return Expression(self.at(f"class_list_get(&{owner.code},&({self.number(index)}))",node),kind)

    def store_reference(self, reference, value, node):
        if reference[0]=="name":
            return self.assign(reference[1],value)
        if reference[0]=="field":
            _,owner,plan,index,kind=reference
            return f"{owner.code}.borrow_mut().field_{index}=Some({self.coerce(value,kind,node)});"
        _,owner,index,kind=reference
        setter=f"class_list_set(&{owner.code},&({self.number(index)}),{self.coerce(value,kind,node)})"
        return self.at(setter,node)+";"

    def statements(self, values):
        return "\n".join(self.statement(value)for value in values)

    def statement(self, node):
        if isinstance(node,(ast.ClassDef,ast.FunctionDef,ast.Import,ast.Pass)):
            return ""
        if isinstance(node,ast.Expr):
            if isinstance(node.value,ast.Constant)and type(node.value.value)is str:
                return ""
            return self.expression(node.value).code+";"
        if isinstance(node,ast.Assign):
            if domain(self.kind(node.value))=="map_int":
                if len(node.targets)!=1 or not isinstance(node.targets[0],(ast.Tuple,ast.List)):
                    raise ClassUnsupported(node)
                target=node.targets[0];temporary=self.fresh()
                setup=f"let {temporary}={self.parse_words(node.value,len(target.elts))};"
                return setup+"".join(self.assign(value,Expression(f"{temporary}[{i}].clone()",'int'))
                                     for i,value in enumerate(target.elts))
            setup,value=self.capture(self.expression(node.value))
            return setup+"".join(self.assign(target,Expression(value.code+".clone()",value.kind,value.constant))for target in node.targets)
        if isinstance(node,ast.AugAssign):
            setup,reference=self.reference(node.target)
            old_kind=shape(self.model.augmented[(self.plan.index,id(node))])
            before,old=self.capture(self.load_reference(reference,node.target,old_kind))
            more,right=self.capture(self.expression(node.value))
            wanted=self.kind(node.target)
            if domain(old.kind)=="list"and isinstance(node.op,ast.Add)and domain(right.kind)=="list":
                operation=f"class_list_extend(&{old.code},&{right.code});"
                result=Expression(old.code,old.kind)
            else:
                result=self.binary(node.op,old,right,node,wanted)
                operation=""
            result_setup,result=self.capture(result)
            return setup+before+more+operation+result_setup+self.store_reference(reference,result,node.target)
        if isinstance(node,ast.Return):
            value=Expression("()",'none')if node.value is None else self.expression(node.value)
            return f"return Ok({self.coerce(value,shape(self.plan.result),node)});"
        if isinstance(node,ast.If):
            setup,test=self.capture(self.expression(node.test))
            return setup+f"if {self.truth(test)}{{\n{self.statements(node.body)}\n}}else{{\n{self.statements(node.orelse)}\n}}"
        if isinstance(node,ast.While):
            label=self.fresh()
            self.loops.append(label)
            setup,test=self.capture(self.expression(node.test))
            body=self.statements(node.body)
            self.loops.pop()
            return f"'{label}:loop{{{setup}if !({self.truth(test)}){{break;}}{body}}}"
        if isinstance(node,ast.For):
            return self.for_statement(node)
        if isinstance(node,ast.Break):
            return f"break '{self.loops[-1]};"
        if isinstance(node,ast.Continue):
            return f"continue '{self.loops[-1]};"
        raise ClassUnsupported(node)

    def for_statement(self, node):
        iterable=node.iter
        enumerated=(isinstance(iterable,ast.Call)and isinstance(iterable.func,ast.Name)
                    and iterable.func.id=="enumerate"and domain(self.kind(iterable))=="enumerate")
        source_node=iterable.args[0]if enumerated else iterable
        setup,source=self.capture(self.expression(source_node))
        counter=None
        if enumerated:
            start=self.expression(iterable.args[1])if len(iterable.args)==2 else Expression(self.literal(0),'int',0)
            counter=self.fresh()
            setup+=f"let mut {counter}={self.number(start)};"
        label=self.fresh();self.loops.append(label)
        body=self.statements(node.body)
        self.loops.pop()
        current=self.fresh()
        if domain(source.kind)=="list":
            index=self.fresh()
            setup+=f"let mut {index}=0_usize;"
            advance=self.at(f"{index}.checked_add(1).ok_or_else(||\"OverflowError: list iterator index overflow\".to_owned())",node)
            prefix=f"'{label}:loop{{let {current}={{{source.code}.borrow().get({index}).cloned()}};let Some({current})={current} else{{break;}};{index}={advance};"
            item=Expression(current,source.kind.element)
        elif domain(source.kind)=="range":
            iterator=self.fresh();setup+=f"let mut {iterator}={source.code}.iter();"
            prefix=f"'{label}:while let Some({current})={iterator}.next(){{"
            item=Expression(current,'int')
        elif domain(source.kind)=="tuple":
            kind=None
            for candidate in source.kind.fields:
                if kind is None:kind=candidate
                elif kind!=candidate:
                    if {domain(kind),domain(candidate)}<={"int","bool","int_bool"}:kind='int_bool'
                    else:raise ClassUnsupported(node)
            kind=kind or'int'
            values=[self.coerce(Expression(f"{source.code}.{i}.clone()",old),kind,node)for i,old in enumerate(source.kind.fields)]
            prefix=f"'{label}:for {current} in ["+",".join(values)+"].into_iter(){"
            item=Expression(current,kind)
        else:
            raise ClassUnsupported(node)
        before=""
        if counter is not None:
            saved=self.fresh();before=f"let {saved}={counter}.clone();"
            increment=self.numeric.binary(ast.Add(),_Expression(counter+".clone()","int"),_Expression(self.literal(1),"int",1),node).code
            before+=f"{counter}={increment};"
            item=Expression(f"({saved},{item.code})",TupleType(("int",item.kind)))
        binding=self.assign(node.target,item)
        return setup+prefix+before+binding+body+"}"

    def declaration(self):
        data=[f"let mut {slot}:{self.rust_type(MaybeType(kind))}=None;"for(_,kind),slot in self.slots.items()]
        references=[f"let mut {slot}=false;"for slot in self.reference_slots.values()]
        return "\n".join(data+references)

    def generate(self):
        body=self.statements(self.plan.node.body)
        parameters=[];initial=[]
        for i,name in enumerate(self.plan.parameters+self.plan.keyword_only):
            kind=shape(self.plan.arguments[name]);argument=f"class_argument_{i}"
            parameters.append(f"{argument}:{self.rust_type(kind)}")
            initial.append(f"{self.slot(name,kind)}=Some({argument});")
        result=self.rust_type(shape(self.plan.result))
        if "none"in alternatives(shape(self.plan.result)):
            tail="Ok("+self.coerce(Expression("()","none"),shape(self.plan.result),self.plan.node)+")"
        else:
            tail=f"Err(NativeError{{message:\"RuntimeError: invalid compiled return\".into(),line:{getattr(self.plan.node,'lineno',1)},function:{_string(self.plan.scope)},frames:Vec::new()}})"
        signature="class_scope:ClassScope"+(" ,"+",".join(parameters)if parameters else"")
        return (f"fn {self.function_name(self.plan)}({signature})->ClassFuture<{result}>{{Box::pin(async move{{\n"
                "use std::fmt::Write as _;\n"+self.declaration()+"\n"+"\n".join(initial)+"\n"+body+"\n"+tail+"\n})}")


def _named_helpers(source,wanted):
    """Select complete shared Rust primitives without unrelated owner impls."""
    from .rust_pruning import _lex, _parse
    tokens,comments,pairs=_lex(source)
    selected=[item for item in _parse(source,tokens,comments,pairs)if item.name in wanted]
    if {item.name for item in selected}!=wanted:
        raise ValueError("missing shared native helper")
    return "\n".join(source[item.start:item.end]for item in selected)


def _text_helpers(runtime):
    """Use the shared Unicode-aware repr primitives without object-runtime code."""
    return _named_helpers(runtime.joinpath("text.rs").read_text(encoding="utf-8"),
                          {"TEXT_PRINTABLE","text_property","text_repr_str","text_repr_bytes"})


def _structural_helpers(integer):
    if integer=="bigint":
        index="let index=index.to_i128().ok_or_else(||\"IndexError: list index out of range\".to_string())?;"
        count="if count.is_negative(){return Ok(0);}let count=count.to_i128().ok_or_else(||\"OverflowError: cannot fit 'int' into an index-sized integer\".to_string())?;"
        recursion="let value=value.to_i128().ok_or_else(||\"OverflowError: Python int too large to convert to C int\".to_string())?;"
        from_usize="Int::from_i128(value as i128)"
    else:
        index="let index=*index as i128;"
        count="let count=*count as i128;if count<0{return Ok(0);}"
        recursion="let value=*value as i128;"
        from_usize="value as NativeInt"
    return """
fn class_index(index:&NativeInt,length:usize)->Result<usize,String> {
    """+index+"""
    let index=if index<0{(length as i128).checked_add(index)}else{Some(index)};
    match index{Some(value)if value>=0&&(value as u128)<length as u128=>Ok(value as usize),_=>Err("IndexError: list index out of range".into())}
}
fn class_repetition_count(count:&NativeInt)->Result<usize,String>{
    """+count+"""
    if count>isize::MAX as i128{return Err("OverflowError: cannot fit 'int' into an index-sized integer".into());}Ok(count as usize)
}
fn class_recursion_limit(value:&NativeInt)->Result<usize,String>{
    """+recursion+"""
    if value<i32::MIN as i128||value>i32::MAX as i128{return Err("OverflowError: Python int too large to convert to C int".into());}
    if value<1{return Err("ValueError: recursion limit must be greater or equal than 1".into());}Ok(value as usize)
}
fn class_from_usize(value:usize)->NativeInt{"""+from_usize+"}" 


def _class_layouts(model,emitter):
    result=[]
    for owner in model.classes.values():
        if not owner.used:continue
        fields=list(owner.fields.values())
        members=",".join(f"field_{i}:{emitter.rust_type(MaybeType(shape(value.cell)))}"for i,value in enumerate(fields))
        result.append(f"struct ClassData_{owner.index}{{{members}}}\ntype ClassHandle_{owner.index}=Rc<RefCell<ClassData_{owner.index}>>;")
        for i,value in enumerate(fields):
            message=_string(f"AttributeError: '{owner.node.name}' object has no attribute '{value.name}'")
            result.append(f"fn class_get_{owner.index}_{i}(value:&ClassHandle_{owner.index})->Result<{emitter.rust_type(shape(value.cell))},String>{{value.borrow().field_{i}.clone().ok_or_else(||{message}.to_owned())}}")
        result.append(f"impl ClassDisplay for ClassHandle_{owner.index}{{fn class_str(&self)->String{{format!(\"<__main__.{owner.node.name} object at 0x{{:x}}>\",Rc::as_ptr(self)as usize)}}}}")
        constructor=owner.methods.get("__init__")
        params=[];args=[]
        if constructor:
            for i,name in enumerate(constructor.parameters[1:]+constructor.keyword_only):
                params.append(f"argument_{i}:{emitter.rust_type(shape(constructor.arguments[name]))}")
                args.append(f"argument_{i}")
        signature="class_scope:ClassScope"+(","+",".join(params)if params else"")
        initialize=",".join(f"field_{i}:None"for i in range(len(fields)))
        body=f"let object=Rc::new(RefCell::new(ClassData_{owner.index}{{{initialize}}}));"
        if constructor:
            body+=f"class_function_{constructor.index}(class_scope.clone(),object.clone()"+(","+",".join(args)if args else"")+ ").await?;"
        result.append(f"fn class_construct_{owner.index}({signature})->ClassFuture<ClassHandle_{owner.index}>{{Box::pin(async move{{{body}Ok(object)}})}}")
    return "\n".join(result)


def try_generate_classes(source,filename,integer,*,trusted_imports=frozenset(),prune_output=True,diagnostic_out=None,unit=None,
                         string_mode="ascii"):
    """Lower a proved closed class program to concrete Rust and compiled futures."""
    from .frontend import build_program, native_namespace_diagnostic
    from .diagnostics import CompilationError
    try:
        if unit is None:
            from dataclasses import replace
            unit = build_program(source, filename).main
            # Internal callers historically opt into standard-module helpers.
            # Restrict that proof to origins verified by the shared resolver.
            unit = replace(unit, native_imports=unit.native_imports.intersection(trusted_imports))
        unit.check_identity(source, filename)
    except CompilationError as error:
        if diagnostic_out is not None:diagnostic_out.append(error.diagnostic)
        return None
    namespace_error = native_namespace_diagnostic(unit)
    if namespace_error is not None:
        if diagnostic_out is not None:diagnostic_out.append(namespace_error)
        return None
    trusted_imports = unit.native_imports
    try:
        if integer not in {"i64","i128","bigint"}:raise ClassUnsupported(ast.Module(body=[],type_ignores=[]))
        tree=unit.tree
        model=Model(tree,filename,integer,trusted_imports,unit=unit,string_mode=string_mode).run()
        emitters=[Emitter(model,plan)for plan in model.plans if plan.reachable]
        bodies=[emitter.generate()for emitter in emitters]
        layouts=_class_layouts(model,emitters[0])
        unions={}
        def add_kind(kind):
            if isinstance(kind,UnionType):
                unions[kind]=None
                for alternative in kind.alternatives:add_kind(alternative)
            elif isinstance(kind,(NullableType,MaybeType)):add_kind(kind.value)
            elif isinstance(kind,TupleType):
                for field in kind.fields:add_kind(field)
            elif isinstance(kind,ListType):add_kind(kind.element)
        for value in model.records.values():add_kind(shape(value))
        for plan in model.plans:
            if plan.reachable:
                add_kind(shape(plan.result))
                for value in plan.arguments.values():add_kind(shape(value))
        for owner in model.classes.values():
            if owner.used:
                for value in owner.fields.values():add_kind(shape(value.cell))
        layouts="\n".join(union_declaration(kind,emitters[0].rust_type)for kind in unions)+"\n"+layouts
    except (SyntaxError,_Unsupported,RecursionError)as error:
        if diagnostic_out is not None:diagnostic_out.append(_direct_diagnostic(source,filename,error,unit=unit))
        return None
    from .native import _HELPERS,_OUTPUT_HELPERS,_INPUT_HELPERS,_SCALAR_UNION_HELPERS
    runtime=files("py2fastrust").joinpath("runtime")
    pieces=["// Generated by py2fastrust: direct typed class AOT backend.\n#![allow(dead_code,unused_imports,unused_variables,unused_mut,unused_assignments,unused_parens,unused_labels,non_camel_case_types,unreachable_code)]\n",
            f"const INT_BITS:u32={0 if integer=='bigint'else 64 if integer=='i64'else 128};\ntype NativeInt={'Int'if integer=='bigint'else integer};\n"]
    for license_name in("PYTHON_LICENSE.txt","UNICODE_LICENSE.txt"):
        value=files("py2fastrust").joinpath("stdlib",license_name).read_text(encoding="utf-8")
        pieces.append("\n".join("// "+line for line in value.splitlines()))
    pieces.append(runtime.joinpath("integer.rs").read_text(encoding="utf-8"))
    if integer=="bigint":
        from .native_bigint import _HELPERS as bigint_helpers
        pieces.extend([bigint_helpers,_named_helpers(_INPUT_HELPERS,{"native_space"}),
                       "fn native_parse_integer(value:&str)->Result<Int,String>{Int::parse(value,10)}"])
    else:
        from .native_scalar import SCALAR_HELPERS
        from .native_integer_parsing import render_helpers as parsing_helpers
        pieces.extend([_HELPERS,_named_helpers(_INPUT_HELPERS,{"native_space"}),parsing_helpers(string_mode),_SCALAR_UNION_HELPERS,SCALAR_HELPERS,
                       "impl ClassDisplay for f64 {fn class_str(&self)->String{native_float_text(*self)}}"])
    if model.sequence_calls:
        from .native_typed_lists import HELPERS as sequence_helpers
        pieces.append(sequence_helpers)
    pieces.extend([_OUTPUT_HELPERS,runtime.joinpath("streaming_io.rs").read_text(encoding="utf-8"),
                   _text_helpers(runtime),_structural_helpers(integer),runtime.joinpath("native_classes.rs").read_text(encoding="utf-8"),layouts,*bodies])
    pieces.append("fn main(){use std::io::Write as _;let scope=ClassScope::new();let result=class_execute(scope.clone(),class_function_0(scope.clone()));\n"
                  "std::io::stdout().write_all(scope.io.borrow().output.as_bytes()).unwrap();\n"
                  'if let Err(error)=result {eprintln!("Traceback (most recent call last):");\n'
                  'for &(line,function)in error.frames.iter().rev(){\n'
                  f'eprintln!("  File {{:?}}, line {{}}, in {{}}",{_string(filename)},line,function);}}\n'
                  f'eprintln!("  File {{:?}}, line {{}}, in {{}}\\n{{}}",{_string(filename)},error.line,error.function,error.message);std::process::exit(1);}}}}')
    result="\n".join(pieces)
    from .native_text_policy import apply_text_policy
    result=apply_text_policy(result,string_mode)
    from .native_cached_text import apply_cached_text
    result=apply_cached_text(result,string_mode)
    if prune_output:
        from .rust_pruning import prune_rust_source
        result=prune_rust_source(result)
    from .native_notices import retain_native_notices
    return retain_native_notices(result)
