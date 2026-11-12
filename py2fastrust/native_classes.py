"""Direct, typed class lowering with compiled Rust continuations.

The proof covers a closed collection of ordinary classes and functions. Each
instance has a concrete Rust layout. Lists use ownership-selected vectors or
shared typed handles. Rust compiles function bodies into futures; a caller stack
polls them without interpreting Python operations or growing the host stack.
"""

import ast
import symtable
from dataclasses import dataclass, field
from importlib.resources import files
from types import SimpleNamespace

from .native import _Expression, _Unsupported, _direct_diagnostic, _string, _FunctionPlans
from .call_semantics import FunctionSignature, CallBindingError, normalize_call
from .references import CORE_BUILTINS, BuiltinIdentity, UnknownReference, resolve_static_callable
from .native_types import (TupleType, TupleSequenceType, ListType, MaybeType, NullableType, UnionType,EmptyType,
                           alternatives, union_type, join_types, immutable, render_type,
                           tuple_code, union_declaration)
from .native_types import reference_cloneable
from .native_unions import construct, project, union_kind
from .native_constraints import Solver, SemanticGraph, Variable, value as constraint_value



@dataclass(frozen=True)
class InstanceType:
    """A class-specific leaf; structural/value kinds use the shared descriptors."""
    name: str
    _native_reference_cloneable=True

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
    if getattr(kind,'_native_exception_class',False):return 'exception_class'
    if getattr(kind,'_native_exception_value',False):return 'exception_value'
    if getattr(kind,"_native_builtin_singleton",False):return "builtin_singleton"
    if getattr(kind,'_native_cmp_key',False):return 'cmp_key'
    if getattr(kind,'_native_class_deque',False):return 'deque'
    if getattr(kind,'_native_mapping_view',False):return 'dict_view'
    if getattr(kind,"_native_class_mapping",False):return kind.record.category
    if getattr(kind,"_native_class_generator",False):return "generator"
    if getattr(kind,"_native_function_reference",False):return "function"
    if getattr(kind,"_native_namespace_view",False):return "globals_dict"
    if getattr(kind,"_native_class_iterator",False):return "iterator"
    if isinstance(kind, InstanceType):return "object"
    if isinstance(kind, TupleSequenceType):return "tuple_sequence"
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
    if isinstance(kind,(ListType,TupleSequenceType)):return has_float_payload(kind.element)
    return False


class ClassUnsupported(_Unsupported):
    def __init__(self, node, reason=None, **context):
        super().__init__(reason,node=node,**context)


@dataclass(eq=False)
class Cell:
    tag: str | None = None
    args: tuple = ()
    parent: "Cell | None" = None
    list_origins: frozenset | None = field(default=None,repr=False)

    def root(self):
        if self.parent is not None:
            self.parent = self.parent.root()
            return self.parent
        return self


def shape(cell):
    cell = cell.root()
    if getattr(cell.tag,'_native_tuple_record',False):return cell.tag.kind(tuple(shape(value)for value in cell.args))
    if cell.tag == "list":return ListType(shape(cell.args[0]))
    if cell.tag == "tuple":return TupleType(tuple(shape(value)for value in cell.args))
    if cell.tag == "tuple_sequence":return TupleSequenceType(shape(cell.args[0]))
    if cell.tag == "object":return InstanceType(cell.args[0])
    if cell.tag=="function":
        from .native_aot_callables import AotFunctionType
        return AotFunctionType.from_targets(cell.args)
    if cell.tag=="globals_dict":
        from .native_globals_view import GLOBALS_VIEW
        return GLOBALS_VIEW
    if cell.tag in {"enumerate","map_int"}:return StreamType(cell.tag,tuple(shape(value)for value in cell.args))
    if cell.tag == "union":return union_type(*(shape(value)for value in cell.args))
    return cell.tag


def immutable_cell(cell):
    return immutable(shape(cell))


def tuple_cell(cell):
    return cell.root().tag=='tuple'or getattr(cell.root().tag,'_native_tuple_record',False)


def merge(left, right, node,*,allow_unresolved=False):
    left, right = left.root(), right.root()
    if left is right:
        return left
    if left.args or right.args:
        from .native_class_storage import check_merge
        check_merge(left,right,node)
    if left.tag is None:
        left.parent = right
        return right
    if right.tag is None:
        right.parent = left
        return left
    if isinstance(left.tag,EmptyType):
        left.parent=right
        return right
    if isinstance(right.tag,EmptyType):
        right.parent=left
        return left
    if left.tag==right.tag=="function":
        from .native_aot_callables import ordered_targets
        left.args=ordered_targets(left.args+right.args)
        right.parent=left
        return left
    if {left.tag, right.tag} <= {"int", "bool", "int_bool"}:
        tag = join_types(left.tag,right.tag)
        right.parent = left
        left.tag = tag
        return left
    if left.tag != right.tag or left.tag=="union"or(left.tag=="tuple"and len(left.args)!=len(right.args))or(left.tag==right.tag=="object"and left.args!=right.args):
        from .native_class_storage import shared_element
        # ListType is an owned Vec in ordinary lowering, but the class ABI
        # stores it as a shared ClassList handle. Prove that actual ABI here.
        if not shared_element(shape(left),allow_unresolved=allow_unresolved)or not shared_element(shape(right),allow_unresolved=allow_unresolved):raise ClassUnsupported(node)
        # Keep constructor payloads separate from the outer joined ABI. Mutable
        # allocation shapes are never widened into a union by this solver.
        candidates=[]
        for value in (left,right):
            choices=value.args if value.tag=="union"else(Cell(value.tag,value.args,list_origins=value.list_origins),)
            for choice in choices:
                old=next((old for old in candidates if shape(choice)==shape(old)),None)
                if old is None:candidates.append(choice)
                else:
                    from .native_list_positions import join_origins
                    join_origins(old,choice)
        left.tag,left.args="union",tuple(candidates)
        right.parent=left
        return left
    if left.tag in {"list", "tuple", "tuple_sequence", "enumerate", "map_int"}or getattr(left.tag,'_native_tuple_record',False):
        if len(left.args) != len(right.args):
            raise ClassUnsupported(node)
        if left.tag=='list':
            left.list_origins=(None if left.list_origins is None or right.list_origins is None
                               else left.list_origins|right.list_origins)
        for a, b in zip(left.args, right.args):
            merge(a, b, node,allow_unresolved=allow_unresolved)
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
    body_plan: object = None
    source_unit: object = None
    module_name: str = "__main__"
    canonical_name: str | None = None


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
    class_body: ClassPlan | None = None
    source_unit: object = None
    module_name: str = "__main__"
    definition_key: object = None

    @property
    def runtime_parameters(self):
        return self.signature.parameters if self.signature is not None else tuple(self.parameters+self.keyword_only)

    @property
    def scope(self):
        return self.node.name if isinstance(self.node,(ast.FunctionDef,ast.ClassDef))else "<lambda>"if isinstance(self.node,ast.Lambda)else "<module>"

    def name(self, value):
        return mangle(value, self.owner.node.name if self.owner else None)


class Environment(dict):
    """Possible typed bindings plus names definitely assigned on this path."""
    def __init__(self,values=(),*,definite=None):
        super().__init__(values)
        known=getattr(values,"definite",None)if definite is None else definite
        self.definite=set(self)if known is None else set(known)
        if hasattr(values,"enclosing_global_names"):
            self.enclosing_global_names=values.enclosing_global_names


class Model:
    BUILTINS = {"input", "print", "range", "len", "int", "bool", "str", "float",
                "list", "map", "enumerate", "filter", "iter", "next", "any", "all", "sum", "min", "max", "abs", "id"}
    DATA = {"exception_class","exception_value","builtin_singleton", "int", "bool", "int_bool", "union", "str", "bytes", "float", "none", "object", "function", "list", "tuple", "tuple_sequence", "range","globals_dict","dict","set","dict_view"}
    INTRINSICS = {"sys", "stdin", "stdin_buffer", "reader_text", "reader_bytes", "read_text", "read_bytes"}

    def __init__(self, tree, filename, integer, trusted_imports, unit=None, string_mode="ascii"):
        self.tree, self.filename, self.integer = tree, filename, integer
        self.string_mode = string_mode
        self.string_repr_required = False
        self.unit = unit
        self.trusted_imports = trusted_imports
        self.classes, self.functions = {}, _FunctionPlans()
        self.function_families = {}
        self.call_edges = {}
        self.call_edges_by_site = {}
        self.plans = []
        self.node_cells = {}
        # Storage members receive directional value constraints. Their incoming
        # immutable values retain independent types, just as in ordinary scopes.
        self.value_constraints = Solver(self.semantic_graph(unit) if unit is not None else SimpleNamespace())
        self.member_allocations = {}
        self.value_variables = {}
        self.constructors = {}
        self.sequence_calls = {}
        self.condition_calls = set()
        self.comprehensions = {}
        from .native_class_comprehensions import target_ordinals
        self.comprehension_targets = target_ordinals(tree,unit)
        self.records = {}
        self.augmented = {}
        self.module = FunctionPlan(tree, 0, reachable=True, visible_definitions=set(),global_names=set())
        self.bind_plan_origin(self.module,tree)
        merge(self.module.result, Cell("none"), tree)
        self.plans.append(self.module)
        self.loop_depth = 0
        self.loop_edges = []
        self.loop_continues = []
        self.loop_feedback = {}
        self.final = False
        self.global_symbols = {}
        # Global binding versions through loops are not represented yet.
        # A possible module-owned write forbids assuming the default builtin,
        # including a write reached only on a later loop iteration.
        self.global_written_names=frozenset(binding.name for binding in unit.bindings
            if self.module_owner(binding.owner) and binding.role not in {"load","parameter"})if unit is not None else frozenset()
        self.namespace=self.create_namespace()
        from .native_class_deques import Deques
        self.deques=Deques(self)
        from .native_class_mappings import Mappings
        self.mappings=Mappings(self)
        from .native_context_managers import ContextManagers
        self.context_managers=ContextManagers(self)
        from .native_class_operators import Operators
        self.operators=Operators(self)
        self.discover()
        from .native_lambda_cells import LambdaCells
        self.lambda_cells=LambdaCells(self)
        self.lexical=self.create_lexical_cells()
        self.callable_cells=self.create_callable_cells()
        from .native_class_iterators import Iterators
        self.iterators=Iterators(self)
        from .native_source_generators import prepare as prepare_source_generators
        prepare_source_generators(self)
        from .native_starred_calls import ExpandedCalls
        self.expanded_calls=ExpandedCalls(self)
        from .native_immediate_generators import Generators
        self.generators=Generators(self)
        from .native_exception_values import Exceptions
        self.exceptions=Exceptions(self)
        from .native_frame_specialization import Specializations
        self.specializations=Specializations(self)

    def semantic_graph(self,unit):return SemanticGraph(unit)

    def create_namespace(self):
        from .native_class_globals import Namespace
        return Namespace(self)

    def create_lexical_cells(self):
        from .native_lexical_cells import LexicalCells
        return LexicalCells(self)

    def create_callable_cells(self):
        from .native_aot_callables import CallableCells
        return CallableCells(self)

    def emitter(self,plan):return Emitter(self,plan)

    def finish_runtime(self,source):return source

    def class_runtime_context(self,owner):return "","",""

    def module_owner(self,scope):return scope is not None and self.unit.scopes[scope].kind=="module"

    def iter_nodes(self):
        from .native_annotations import executable_nodes
        return executable_nodes(self.tree)

    def iter_bindings(self):
        # Lazy annotation thunks retain free lexical cells without evaluating
        # their expressions. Keep that ownership metadata for environment
        # retention, even though iter_nodes excludes their executable plans.
        return iter(self.unit.bindings)if self.unit is not None else iter(())

    def is_module_plan(self,plan):return plan is self.module

    def definition_name(self,node):
        registry=getattr(self,"class_namespaces",None)
        if registry is not None and id(node)in registry.keys:return registry.keys[id(node)]
        return self.unit.name_for(node)if self.unit is not None else node.name

    @staticmethod
    def class_key(owner):return owner.canonical_name or owner.node.name

    def display_name(self,name):
        return self.unit.display_name(name)if hasattr(self.unit,"display_name")else name

    def bind_plan_origin(self,plan,node):
        if self.unit is None:return
        source=self.unit.original_unit(node)if hasattr(self.unit,"original_unit")else self.unit
        plan.source_unit=source
        plan.module_name=source.name
        plan.definition_key=(source.name,source.ordinal(node))

    def resolved_name(self, plan, node):
        if self.unit is not None and isinstance(node,ast.alias):
            return self.namespace.owners[self.unit.ordinal(node)].name
        if self.unit is not None:return self.unit.name_for(node)
        raw=node.id if isinstance(node,ast.Name)else node.attr if isinstance(node,ast.Attribute)else node.arg
        return plan.name(raw)

    @staticmethod
    def display_name(name):
        """Python spelling can differ from a linked module's canonical key."""
        return getattr(name,"python_name",name)

    def module_owner(self,scope):
        if scope is None:return False
        if self.unit is None:return scope==0
        predicate=getattr(self.unit,"is_module_scope",None)
        return predicate(scope)if predicate is not None else self.unit.scopes[scope].kind=="module"

    def builtin_identity(self,plan,node,environment):
        name=self.resolved_name(plan,node)
        lexical=getattr(self,"lexical",None)
        if lexical is not None and isinstance(node,ast.Name)and(lexical.field_for(node)is not None or lexical.function_for(node)is not None):
            return UnknownReference(name,"name denotes a lexical closure binding")
        if name in self.classes or name in self.functions:
            return UnknownReference(name,"name denotes a source definition")
        return resolve_static_callable(node,environment,local_names=plan.declared,
            global_bound_names=(set(plan.global_names or ())if not self.is_module_plan(plan) else set(environment))|self.global_written_names,
            name_for=self.unit.name_for if self.unit is not None else None,
            private_owner=plan.owner.node.name if plan.owner else None,function_scope=not self.is_module_plan(plan),
            builtin_spelling=self.display_name)

    def cell(self, plan, node, tag=None, args=(),*,identity=None):
        key = (plan.index, id(node))if identity is None else(plan.index,id(node),identity)
        result = self.node_cells.setdefault(key, Cell())
        if tag is not None:
            origins=None
            if tag=='list':
                site=self.unit.ordinal(node)if self.unit is not None else id(node)
                allocation=self.value_constraints.allocation(site,'list',('class',plan.index)if identity is None else('class',plan.index,identity))
                origins=frozenset({allocation})
            self.constructors.setdefault(key,Cell(tag,tuple(args),list_origins=origins))
            merge(result, Cell(tag, tuple(args),list_origins=origins), node,allow_unresolved=not self.final)
        if identity is None:self.records[key] = result
        if tag == "list":
            site=self.unit.ordinal(node) if self.unit is not None else id(node)
            allocation=self.value_constraints.allocation(site,"list",("class",plan.index)if identity is None else("class",plan.index,identity))
            self.member_allocations[result.root().args[0]]=allocation
            from .native_class_allocation_facts import register
            register(self,allocation,result.root().args[0])
            from .native_list_positions import register as register_positions
            register_positions(self,allocation,result.root().args[0],node)
        return result

    @staticmethod
    def flow_copy(cell):
        """Copy value shapes while preserving shared mutable allocation leaves."""
        cell=cell.root()
        if cell.tag in {"tuple","union","enumerate","map_int"}or getattr(cell.tag,'_native_tuple_record',False):
            return Cell(cell.tag,tuple(Model.flow_copy(child)for child in cell.args))
        return Cell(cell.tag,cell.args,list_origins=cell.list_origins)

    @staticmethod
    def cell_for_kind(kind):
        if getattr(kind,'_native_named_tuple',False):
            return Cell(kind.record.tag,tuple(Model.cell_for_kind(value)for value in kind.fields))
        if getattr(kind,"_native_function_reference",False):return Cell("function",kind.targets)
        if getattr(kind,"_native_namespace_view",False):return Cell("globals_dict")
        if isinstance(kind,NullableType):
            return Cell("union",(Cell("none"),Model.cell_for_kind(kind.value)))
        if isinstance(kind,UnionType):
            return Cell("union",tuple(Model.cell_for_kind(choice)for choice in kind.alternatives))
        if isinstance(kind,TupleType):
            return Cell("tuple",tuple(Model.cell_for_kind(child)for child in kind.fields))
        if isinstance(kind,TupleSequenceType):return Cell("tuple_sequence",(Model.cell_for_kind(kind.element),))
        return Cell(kind)

    def contribute(self,destination,source,node):
        """A value flowing into storage never changes the source's value type."""
        if self.namespace.contribute(destination,source,node):return destination
        source=self.namespace.detached(source).root()
        if source.tag is None:return destination
        kind=shape(source)
        if immutable(kind):
            allocation=self.member_allocations.get(destination)
            if allocation is not None:variable=Variable(allocation.site,"element")
            else:
                variable=self.value_variables.get(destination)
                if variable is None:
                    variable=Variable(("class_value",len(self.value_variables)),"value")
                    self.value_variables[destination]=variable
            previous=shape(destination)
            if previous is not None and immutable(previous):
                self.value_constraints.constrain(variable,constraint_value(previous))
            if allocation is not None:
                self.value_constraints.insert(constraint_value(allocation),"element",constraint_value(kind))
            else:self.value_constraints.constrain(variable,constraint_value(kind))
            resolved=self.value_constraints.kind(constraint_value(variable))
            return merge(destination,self.cell_for_kind(resolved),node,allow_unresolved=not self.final)
        return merge(destination,self.flow_copy(source),node,allow_unresolved=not self.final)

    def remember(self, plan, node, result):
        if isinstance(node,ast.expr)and not isinstance(getattr(node,'ctx',None),(ast.Store,ast.Del)):
            from .native_typing_aliases import runtime_value
            runtime_value(result,node,self,plan)
        self.records[(plan.index, id(node))] = result
        return result

    def field(self, owner, name, node, writing=False):
        if name in owner.methods:
            if writing:
                raise ClassUnsupported(node,"shadowing this method on an instance needs instance-dictionary storage and descriptor lookup precedence; that per-instance method replacement is not implemented",proof="instance method shadowing and descriptor lookup")
            raise ClassUnsupported(node,"reading this method as a value requires a bound-method carrier retaining its receiver; direct method calls are supported, but storing or passing that bound method is not implemented",proof="bound receiver lifetime and callable identity")
        if name.startswith("__") and name.endswith("__"):
            raise ClassUnsupported(node)
        result = owner.fields.setdefault(name, Field(name))
        result.written |= writing
        return result.cell

    def function(self, node, owner=None, *, receiver_kind=None):
        name=getattr(node,"name","<lambda>")
        if node.args.kwarg:
            raise ClassUnsupported(node,"variadic keyword arguments need dictionary packing and native argument-frame binding; that keyword storage is not implemented on the class path",operation=f"signature of function {name!r}")
        registry=getattr(self,"class_namespaces",None)
        admitted_descriptor=(owner is not None and registry is not None and
                             registry.member(owner,self.unit.name_for(node)).descriptor!="function")
        if getattr(node,"decorator_list",())and not admitted_descriptor:
            raise ClassUnsupported(node.decorator_list[0],"decorator calls can replace the method/function object at definition time; that native decorated-callable capture is not implemented on the class path",operation=f"decorator of function {name!r}")
        if getattr(node,"type_params",()):
            raise ClassUnsupported(node,"generic type-parameter objects and lazy bound/default evaluation are not implemented on the class path",operation=f"generic function definition {name!r}")
        arguments = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
        plan = FunctionPlan(node, len(self.plans), owner)
        self.bind_plan_origin(plan,node)
        if self.unit is not None:
            signature=self.unit.signature_for(node)
        else:
            locals_at_definition={self.resolved_name(plan,value)for value in ast.walk(node)
                                  if isinstance(value,ast.Name)and isinstance(value.ctx,(ast.Store,ast.Del))}
            locals_at_definition.update(self.resolved_name(plan,value)for value in arguments)
            signature=FunctionSignature.from_ast(node,name_for=lambda arg:self.resolved_name(plan,arg),local_names=locals_at_definition)
        plan.signature=signature
        from .native_variadic import initialize
        initialize(plan)
        plan.parameters=list(signature.positional)
        plan.positional_only=set(signature.positional_only)
        plan.keyword_only=list(signature.keyword_only)
        for name in signature.parameters:plan.arguments[name]=Cell()
        plan.declared=set(signature.local_names)
        defaults=[(slot.name,slot.expression)for slot in signature.defaults]
        for name, value in defaults:
            literal = value.operand if isinstance(value, ast.UnaryOp) and isinstance(value.op, (ast.UAdd, ast.USub)) else value
            plan.defaults[name] = value
            constant=(isinstance(literal,ast.Constant)and type(literal.value)in {int,bool,float,str,type(None)}
                      and (not isinstance(value,ast.UnaryOp)or type(literal.value)in {int,bool,float}))
            if not constant:
                plan.default_cells[name]=Cell()
                self.namespace.defaults[(plan.index,name)]=plan.default_cells[name]
                continue
            # These are total, immutable literal defaults. Capture their value
            # once at definition planning, including unused methods.
            plan.default_cells[name]=self.expression(plan,value,{})
            captured=literal.value
            if isinstance(value,ast.UnaryOp):
                captured=-captured if isinstance(value.op,ast.USub)else +captured
            plan.default_literals[name]=captured
        from .native_class_descriptors import DEFERRED_RECEIVER
        if owner and plan.parameters and receiver_kind is not DEFERRED_RECEIVER:
            value=Cell("object",(self.class_key(owner),))if receiver_kind is None else self.cell_for_kind(receiver_kind)
            merge(plan.arguments[plan.parameters[0]],value,node)
        from .native_lexical_cells import own_return_values
        from .native_source_generators import initialize as initialize_generator
        generator=initialize_generator(self,plan)
        if not generator and not any(value is not None and not(isinstance(value,ast.Constant)and value.value is None)
                   for value in own_return_values(self.unit,node)):
            merge(plan.result, Cell("none"), node)
        self.plans.append(plan)
        return plan

    def register_function(self, node, key):
        """Keep each source event separate from its current binding name."""
        plan = self.functions.definitions.get(node)
        if plan is not None:return plan
        plan = self.function(node)
        self.functions.definitions[node] = plan
        self.function_families.setdefault(key, []).append(plan)
        self.functions[key] = plan
        return plan

    def function_versions(self, name):
        return tuple(self.function_families.get(name, ()))

    def discover(self):
        effects = False
        names = set()
        from .native_annotations import future_directive,class_body_statement,class_body_effect
        for node in self.tree.body:
            if future_directive(node):continue
            if isinstance(node, ast.ClassDef):
                if node.name in names or node.name in self.global_symbols or node.bases or node.keywords or node.decorator_list or node.type_params:
                    raise ClassUnsupported(node)
                self.discover_class(node,self.definition_name(node))
                names.add(node.name)
            elif isinstance(node, ast.FunctionDef):
                if (node.name in names and node.name not in self.functions) or node.name in self.global_symbols:
                    raise ClassUnsupported(node)
                self.register_function(node, node.name)
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
        binding_owners={binding.node:binding.owner for binding in self.unit.bindings}if self.unit is not None else{}
        for value in self.iter_nodes():
            if isinstance(value, ast.Name) and isinstance(value.ctx, (ast.Store, ast.Del)) and value.id in names:
                site=self.unit.ordinal(value)if self.unit is not None else id(value)
                if value.id in self.functions:continue
                if self.unit is not None and binding_owners.get(site)!=0:continue
                if site not in self.comprehension_targets:raise ClassUnsupported(value)
            if isinstance(value, ast.arg) and value.arg in names:
                if self.unit is None or binding_owners.get(self.unit.ordinal(value))==0:raise ClassUnsupported(value)

    def discover_class(self,node,key,*,parent=None):
        """Register one original class AST under its canonical definition key."""
        registry=getattr(self,"class_namespaces",None)
        if node.bases and registry is None or node.keywords or node.decorator_list or node.type_params:
            raise ClassUnsupported(node)
        owner=ClassPlan(node,len(self.classes),canonical_name=key)
        if self.unit is not None:
            owner.source_unit=self.unit.original_unit(node)if hasattr(self.unit,"original_unit")else self.unit
            owner.module_name=owner.source_unit.name
        self.classes[key]=owner
        registry=getattr(self,"class_namespaces",None)
        if registry is not None:registry.register(owner,parent)
        if node.bases:registry.named_tuples.plan(owner)
        from .native_annotations import class_body_statement,class_body_effect
        for member in node.body:
            if isinstance(member,ast.Pass)or isinstance(member,ast.Expr)and isinstance(member.value,ast.Constant)and type(member.value.value)is str:
                continue
            if class_body_statement(member):continue
            if registry is not None and isinstance(member,ast.ClassDef):
                child=self.discover_class(member,registry.nested_key(owner,member),parent=owner)
                registry.register_child(owner,member,child)
                continue
            if registry is not None and registry.class_statement(member):continue
            if not isinstance(member,ast.FunctionDef):
                if isinstance(member,ast.If):
                    raise ClassUnsupported(member,'conditional class-body publication needs optional class-slot binding and fallback semantics; that class publication control flow is not implemented',proof='conditional class namespace publication')
                raise ClassUnsupported(member)
            from .native_class_operators import SUPPORTED_SLOTS
            if member.name.startswith("__")and member.name.endswith("__")and member.name not in {"__init__","__enter__","__exit__"}|SUPPORTED_SLOTS:
                protocol="truth-value"if member.name in {"__bool__","__len__"}else"special-method"
                raise ClassUnsupported(member,f"class {node.name!r} defines {member.name}; native {protocol} protocol dispatch for this override is not implemented",operation=f"special method {node.name+'.'+member.name!r}",proof=f"Python {member.name} protocol dispatch")
            name=self.unit.name_for(member)if self.unit is not None else mangle(member.name,node.name)
            if name in owner.methods:
                raise ClassUnsupported(member,'source class function '+repr(member.name)+' is defined more than once; preserving each class-body function publication and its captured aliases/defaults requires a versioned class-function plan that is not implemented',proof='versioned class function publication')
            receiver_kind=registry.receiver_kind(owner,member)if registry is not None else None
            owner.methods[name]=self.function(member,owner,receiver_kind=receiver_kind)
            if registry is not None:registry.register_method(owner,name,owner.methods[name])
        from .native_source_display import plan_aliases as plan_display_aliases
        plan_display_aliases(self,owner)
        if (registry is not None or any(name not in method.default_literals for method in owner.methods.values()for name in method.defaults)
                or any(class_body_effect(member)for member in node.body)):
            body=FunctionPlan(node,len(self.plans),owner,class_body=owner)
            self.bind_plan_origin(body,node)
            merge(body.result,Cell("none"),node)
            owner.body_plan=body
            self.plans.append(body)
        return owner

    def canonical_local(self, plan, name, value):
        values = plan.locals.setdefault(name, [])
        if not any(existing is value for existing in values):
            values.append(value)

    def snapshot(self):
        from .native_class_extrema import snapshot as extrema_snapshot
        from .native_typing_metadata import snapshot as metadata_snapshot
        from .native_list_positions import snapshot as position_snapshot
        return (tuple((plan.reachable, None if plan.visible_definitions is None else tuple(sorted(plan.visible_definitions)), None if plan.global_names is None else tuple(sorted(plan.global_names)), shape(plan.result), tuple((name, shape(cell)) for name, cell in plan.arguments.items())) for plan in self.plans),
                tuple((owner.node.name, tuple((name, shape(value.cell), value.written) for name, value in owner.fields.items())) for owner in self.classes.values()),
                tuple(sorted((key, shape(value)) for key, value in self.records.items())),self.namespace.snapshot(),self.lexical.snapshot(),self.iterators.snapshot(),self.mappings.snapshot(),self.deques.snapshot(),self.expanded_calls.snapshot(),self.generators.snapshot(),extrema_snapshot(self),metadata_snapshot(self),
                tuple((key,tuple((name,shape(value))for name,value in sorted(state.items())),tuple(sorted(state.definite)))
                      for key,state in sorted(self.loop_feedback.items())),
                self.class_namespaces.named_tuples.snapshot()if hasattr(self,'class_namespaces')else(),
                tuple(tuple(shape(value)for value in record.arguments)for record in self.exceptions.records),position_snapshot(self),
                tuple((key,member.descriptor)for key,member in sorted(self.class_namespaces.members.items()))if hasattr(self,'class_namespaces')else())

    def analyze_body(self,plan,environment):
        if isinstance(plan.node,ast.Lambda):
            environment=Environment(environment)
            self.contribute(plan.result,self.expression(plan,plan.node.body,environment),plan.node.body)
            return None
        result=self.block(plan,plan.node.body,environment)
        if getattr(plan,'source_generator',None)is not None:return None
        if hasattr(self,'class_namespaces'):self.class_namespaces.named_tuples.finish_body(plan,result or environment)
        return result

    def infer_until_stable(self):
        from .native_inference_worklist import solve
        solve(self)
    def run(self):
        if self.unit is not None:
            nodes={self.unit.ordinal(node):node for node in self.iter_nodes()}
            for binding in self.unit.bindings:
                if (self.module_owner(binding.owner)and binding.role in {"store","delete"}
                        and binding.name in self.global_symbols and not self.namespace.eligible(binding.name)):
                    raise ClassUnsupported(nodes[binding.node],"rebinding or deleting this imported reference needs namespace-owned module/callable object storage; the existing static module adapter supports reads and member calls but cannot preserve this binding's mutation",proof="stored imported-reference binding identity and lifetime")
        self.infer_until_stable()
        from .native_variadic import default_empty
        default_empty(self)
        self.expanded_calls.default_empty()
        self.namespace.default_uninhabited()
        self.lexical.default_uninhabited()
        self.mappings.default_uninhabited()
        self.deques.default_uninhabited()
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
        self.specializations.enable()
        if self.specializations.enabled:self.infer_until_stable()
        self.final = True
        self.reached_statements=set()if hasattr(self,'type_guard_cells')or getattr(self,'loop_reachability_used',False)or self.exceptions.raises or getattr(self,'native_abrupt_calls_used',False)or getattr(self,'native_exit_used',False)or getattr(self,'source_generators_used',False)else None
        self.module.visible_definitions = set()
        self.block(self.module, self.tree.body, dict(self.global_symbols))
        for plan in self.plans[1:]:
            if plan.reachable:
                self.lexical.seed_arguments(plan)
                global_names={name:value for name,value in self.global_symbols.items() if name not in plan.declared}
                self.analyze_body(plan,{**global_names, **plan.arguments})
        from .native_class_allocation_facts import publish
        publish(self)
        self.exceptions.validate()
        from .native_class_storage import validate_instance_graph
        validate_instance_graph(self)
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
        for record in self.deques.records:self.deques.validate(record.kind,record.node,frozenset())
        for record in self.mappings.records:self.mappings.validate(record.kind,record.node,frozenset())
        for record in self.mappings.views.records:self.mappings.views.validate(record.kind,record.node,frozenset())
        for name in self.namespace.active:self.storage(self.namespace.cells[name],self.tree)
        for (index,name),value in self.namespace.defaults.items():self.storage(value,self.plans[index].defaults[name])
        self.lexical.validate()
        return self

    def storage(self, cell, node, field_value=False):
        from .native_class_storage import validate
        validate(cell,node,self.integer,field_value=field_value,model=self)

    def expression(self, plan, node, environment):
        if isinstance(node,(ast.Yield,ast.YieldFrom)):
            from .native_source_generators import analyze_yield
            return analyze_yield(self,plan,node,environment)
        if isinstance(node,ast.JoinedStr):
            from .native_formatting import analyze_joined
            return analyze_joined(self,plan,node,environment)
        mapped=self.mappings.analyze_expression(plan,node,environment)
        if mapped is not None:return mapped
        if isinstance(node,ast.GeneratorExp):return self.generators.analyze(plan,node,environment)
        if isinstance(node,ast.Lambda):return self.lambda_cells.value(plan,node,environment)
        if isinstance(node,ast.ListComp):
            from .native_class_comprehensions import analyze
            return analyze(self,plan,node,environment)
        if isinstance(node,(ast.SetComp,ast.DictComp,ast.GeneratorExp)):
            from .native_diagnostics import comprehension_context,operation_name
            raise ClassUnsupported(node,"the class-aware native path has no comprehension scope/iteration/materialization implementation yet; it must preserve comprehension-local bindings, evaluation order and each allocated element's identity",operation=operation_name(node)+" on the class-aware path",types=comprehension_context(node),proof="comprehension scope and alias-preserving element storage")
        if isinstance(node, ast.Constant):
            from .literal_semantics import Literal
            literal=Literal.from_ast(node)
            if literal is None:
                raise ClassUnsupported(node)
            return self.cell(plan, node, literal.kind)
        if isinstance(node, ast.Name):
            exception=self.exceptions.name(plan,node,environment)
            if exception is not None:return self.remember(plan,node,exception)
            name = self.resolved_name(plan,node)
            binding=self.namespace.owners.get(self.unit.ordinal(node))if self.unit is not None else None
            global_reference=(binding is not None and self.module_owner(binding.owner))if self.unit is not None else plan is self.module or name not in plan.declared
            if name in self.global_symbols and global_reference and name not in(plan.visible_definitions or()):
                from .native_class_builtins import SUPPORTED
                if name not in SUPPORTED or plan is not self.module and plan.class_body is None:
                    raise ClassUnsupported(node,"this imported reference is not definitely bound at this execution point; a namespace-owned imported-object carrier is required for lookup before/after import",proof="import binding initialization and call-context availability")
            from .native_builtin_singletons import analyze as analyze_singleton
            singleton=analyze_singleton(self,plan,node,environment)
            if singleton is not None:return self.remember(plan,node,singleton)
            provider=getattr(self,"callable_cells",None)
            function=provider.value(plan,node,environment)if provider is not None else None
            if function is not None:return self.remember(plan,node,function)
            lexical=self.lexical.read(plan,node,environment)
            if lexical is not None:return self.remember(plan,node,lexical)
            shared=self.namespace.read(plan,node,environment)
            if shared is not None:return self.remember(plan,node,shared)
            if name in environment:
                value=environment[name]
                if (self.is_module_plan(plan) and name in CORE_BUILTINS and value.root().tag in self.INTRINSICS
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
                        joined=self.namespace.join_values(result,value,node,name)
                        result=merge(result,value,node)if joined is None else joined
                    return self.remember(plan,node,result)
                from .native_guard_flow import unbound_local
                missing=unbound_local(self,plan,node,environment)
                if missing is not None:return self.remember(plan,node,missing)
                if not self.final:
                    return self.cell(plan,node)
            if node.id in self.classes:
                raise ClassUnsupported(node,"this source class needs a first-class class object and constructor-dispatch carrier; direct class construction is supported, but stored class objects and metaclass protocols are not implemented",proof="class-object identity and dispatch")
            if node.id in self.functions:
                raise ClassUnsupported(node,"the class-aware path can call this definition by its resolved name, but cannot store/pass its function or class object as a first-class value; native callable/class-object storage and dispatch are not implemented",proof="first-class callable/class-object identity and dispatch")
            if name in self.namespace.implicit_names:
                raise ClassUnsupported(node,f"implicit module binding {name!r} needs its Python initialization and namespace value representation; that implicit namespace entry is not implemented on this typed frame path",proof="implicit module namespace initialization")
            if name in self.namespace.builtin_names:
                raise ClassUnsupported(node,f"this name read needs builtin object {name!r} as a stored value; first-class builtin object storage/dispatch is not implemented on this typed frame path",proof="builtin object value representation")
            raise ClassUnsupported(node)
        if isinstance(node, ast.List):
            result = self.cell(plan, node, "list", (Cell(),))
            values=[self.expression(plan,value,environment)for value in node.elts]
            for value,item in zip(node.elts,values):
                self.contribute(result.root().args[0],item,value)
            from .native_list_positions import literal as literal_positions
            literal_positions(self,result,values,node)
            return result
        if isinstance(node, ast.Tuple):
            return self.cell(plan, node, "tuple", tuple(self.expression(plan, value, environment) for value in node.elts))
        if isinstance(node, ast.Attribute):
            receiver=self.expression(plan,node.value,environment)
            return self.attribute_value(plan,node,receiver,environment)
        if isinstance(node, ast.Subscript):
            if isinstance(node.slice, ast.Slice):
                from .native_frame_slices import analyze
                return analyze(self,plan,node,environment)
            owner = self.expression(plan, node.value, environment).root()
            index = self.expression(plan, node.slice, environment).root()
            captured=self.subscript_item(plan,node,owner,index,environment)
            if captured is not None:return captured
            indexed=self.deques.indexes.analyze_read(plan,node,owner,index)
            if indexed is not None:return indexed
            mapped=self.mappings.analyze_item(plan,node,owner,index,environment)
            if mapped is not None:return mapped
            from .native_list_positions import read as positional_read
            positional=positional_read(self,owner,node.slice)
            if positional is not None:
                if not hasattr(self,'positional_list_reads'):self.positional_list_reads={}
                self.positional_list_reads[(plan.index,id(node))]=positional
                return self.remember(plan,node,positional)
            from .native_union_sequences import analyze_subscript
            indexed=analyze_subscript(self,plan,node,owner,index)
            if indexed is not None:return indexed
            if owner.tag is None and not self.final:
                return self.cell(plan,node)
            if index.tag not in {None,"int","bool","int_bool"}:
                raise ClassUnsupported(node.slice)
            if owner.tag in {"list","tuple_sequence"}:
                return self.remember(plan, node, owner.args[0])
            if(owner.tag == "tuple"or getattr(owner.tag,'_native_tuple_record',False))and isinstance(node.slice, ast.Constant) and type(node.slice.value) is int:
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
            return self.binary(plan, node, node.op, left, right, environment=environment)
        if isinstance(node,ast.NamedExpr):
            value=self.expression(plan,node.value,environment)
            if self.namespace.owns(plan,node.target)and self.is_module_plan(plan):
                self.namespace.active.add(self.resolved_name(plan,node.target))
            self.target(plan,node.target,value,environment)
            return self.remember(plan,node,self.namespace.named_value(plan,node,value))
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.Not):
                self.condition(plan,node.operand,environment)
                return self.cell(plan, node, "bool")
            value = self.expression(plan, node.operand, environment)
            custom=self.operators.unary(plan,node,node.op,value,environment)
            if custom is not None:return custom
            value=value.root()
            if value.tag in {"int","bool","int_bool","float"}:
                if value.tag == "float" and not isinstance(node.op,(ast.UAdd,ast.USub)):
                    raise ClassUnsupported(node)
                return self.cell(plan, node, "float" if value.tag == "float" else "int")
            if value.tag is None and not self.final:
                return self.cell(plan, node)
            raise ClassUnsupported(node)
        if isinstance(node, ast.Compare):
            left=self.expression(plan,node.left,environment)
            result=self.cell(plan,node)
            for index,value in enumerate(node.comparators):
                target=environment if index==0 else Environment(environment)
                skipped=Environment(environment)
                right=self.expression(plan,value,target)
                compared=self.operators.comparison(plan,node,index,node.ops[index],left,right,target)
                if compared is None:compared=Cell('bool')
                self.contribute(result,compared,node)
                if index>0:self.replace_environment(environment,self.join(skipped,target,node))
                left=right
            return result
        if isinstance(node, ast.BoolOp):
            result = self.cell(plan, node)
            for index,value in enumerate(node.values):
                if index==0:item=self.expression(plan,value,environment)
                else:
                    skipped=Environment(environment)
                    taken=Environment(environment)
                    item=self.expression(plan,value,taken)
                    self.replace_environment(environment,self.join(skipped,taken,node))
                self.contribute(result,item,node)
            return result
        if isinstance(node, ast.IfExp):
            self.condition(plan, node.test, environment)
            result = self.cell(plan, node)
            yes=Environment(environment)
            no=Environment(environment)
            self.contribute(result,self.expression(plan,node.body,yes),node)
            self.contribute(result,self.expression(plan,node.orelse,no),node)
            self.replace_environment(environment,self.join(yes,no,node))
            return result
        if isinstance(node, ast.Call):
            result=self.call(plan,node,environment)
            from .native_list_positions import after_call
            after_call(self,plan,node)
            return result
        raise ClassUnsupported(node)

    def _condition_join(self,environment,left,right,node):
        # Local point facts fork at conditional effects. Shared namespace and
        # allocation schemas remain conservative summaries of every path.
        joined=self.join(left,right,node)
        environment.clear();environment.update(joined)
        environment.definite=set(joined.definite)

    def condition(self,plan,node,environment):
        """Infer consumed truth without a mutable value-result union cell."""
        if isinstance(node,ast.BoolOp):
            self.condition(plan,node.values[0],environment)
            for child in node.values[1:]:
                before=Environment(environment);after=Environment(environment)
                self.condition(plan,child,after)
                self._condition_join(environment,before,after,node)
            return self.cell(plan,node,"bool")
        if isinstance(node,ast.IfExp):
            self.condition(plan,node.test,environment)
            yes=Environment(environment);no=Environment(environment)
            self.condition(plan,node.body,yes)
            self.condition(plan,node.orelse,no)
            self._condition_join(environment,yes,no,node)
            return self.cell(plan,node,"bool")
        if isinstance(node,ast.UnaryOp)and isinstance(node.op,ast.Not):
            self.condition(plan,node.operand,environment)
            return self.cell(plan,node,"bool")
        return self.expression(plan,node,environment)

    def binary(self, plan, node, operator, left, right, *, identity=None, environment=None):
        result=self.operators.binary(plan,node,operator,left,right,environment,identity=identity)
        if result is not None:return result
        return self.binary_builtin(plan,node,operator,left,right,identity=identity)

    def binary_builtin(self, plan, node, operator, left, right, *, identity=None):
        cell=lambda tag=None,args=():self.cell(plan,node,tag,args,identity=identity)
        a, b = left.root(), right.root()
        if a.tag is None or b.tag is None:
            if self.final:
                raise ClassUnsupported(node)
            return cell()
        from .native_primitive_ops import analyze,classify
        if isinstance(operator,ast.Pow)and a.tag=='float'and b.tag in {'int','bool','int_bool'}:
            return cell('float')
        if isinstance(operator,ast.Pow)and a.tag in {'int','bool','int_bool'}and b.tag in {'int','bool','int_bool'}:
            from .native_integral_powers import node_kind
            result=cell()
            self.contribute(result,self.cell_for_kind(node_kind(node,self.integer)),node)
            return result
        primitive_tags={"int","bool","int_bool","float","str","bytes","none","function","globals_dict","range","list","tuple"}
        if (a.tag=="union"or b.tag=="union"or a.tag in primitive_tags and b.tag in primitive_tags
                and classify(operator,shape(a),shape(b),self.integer).error is not None):
            return analyze(self,plan,node,operator,left,right,identity=identity)
        if isinstance(operator, ast.Add) and a.tag == b.tag == "list":
            merge(a.args[0], b.args[0], node)
            return cell("list", (a.args[0],))
        if isinstance(operator, ast.Mult) and (a.tag == "list" or b.tag == "list"):
            values, count = (a,b) if a.tag == "list" else (b,a)
            if count.tag not in {"int","bool","int_bool"}:
                raise ClassUnsupported(node)
            return cell("list", (values.args[0],))
        if a.tag == b.tag == "str" and isinstance(operator,ast.Add):
            return cell("str")
        if isinstance(operator,ast.Mult) and "str" in {a.tag,b.tag}:
            other = b if a.tag == "str" else a
            if other.tag not in {"int","bool","int_bool"}:
                raise ClassUnsupported(node)
            return cell("str")
        numeric = {"int","bool","int_bool","float"}
        if a.tag not in numeric or b.tag not in numeric:
            if a.tag=="union"or b.tag=="union":
                raise ClassUnsupported(node,"this arithmetic reads finite binding alternatives without a proved per-alternative numeric/string/container operation; runtime dispatch and TypeError paths for those arithmetic combinations are not implemented on this typed frame path",types=(("left",shape(a)),("right",shape(b))),proof="per-alternative arithmetic and error behavior")
            raise ClassUnsupported(node)
        if "float" in {a.tag,b.tag} or isinstance(operator,ast.Div):
            if self.integer=='bigint'and isinstance(operator,ast.Div)and {a.tag,b.tag}<={'int','bool','int_bool'}:
                return cell('float')
            if not isinstance(operator,(ast.Add,ast.Sub,ast.Mult,ast.Div,ast.FloorDiv,ast.Mod)):
                raise ClassUnsupported(node)
            return cell("float")
        if isinstance(operator,(ast.BitAnd,ast.BitOr,ast.BitXor)) and {a.tag,b.tag} <= {"bool","int_bool"}:
            return cell("bool" if a.tag == b.tag == "bool" else "int_bool")
        if not isinstance(operator,(ast.Add,ast.Sub,ast.Mult,ast.FloorDiv,ast.Mod,ast.Pow,ast.LShift,ast.RShift,ast.BitAnd,ast.BitOr,ast.BitXor)):
            raise ClassUnsupported(node)
        return cell("int")

    def call_global_names(self,caller,callee,environment):
        return (set(getattr(environment,"enclosing_global_names",environment))|set(caller.visible_definitions or ()))if self.is_module_plan(caller)else caller.global_names

    def activate_frame(self,caller,node,callee,environment):
        names=self.call_global_names(caller,callee,environment)
        if names is None:raise ClassUnsupported(node)
        if callee.global_names is None:callee.global_names=set(names)
        else:callee.global_names.update(names)
        callee.reachable = True
        self.call_edges.setdefault(caller.index,set()).add(callee.index)
        self.call_edges_by_site.setdefault((caller.index,id(node)),set()).add(callee.index)
        visible = set(caller.visible_definitions or ())
        if callee.visible_definitions is None:
            callee.visible_definitions = visible
        else:
            callee.visible_definitions.intersection_update(visible)

    def bind_call(self, caller, node, callee, argument_cells, keyword_cells, environment):
        if callee.class_body is None:
            try:normalize_call(node)
            except CallBindingError:raise ClassUnsupported(node)from None
        return self.remember(caller,node,self.bind_captured(caller,node,callee,argument_cells,keyword_cells,environment))

    def bind_captured(self,caller,node,callee,argument_cells,keyword_cells,environment):
        """Shared binding for explicit calls and deferred produced arguments."""
        try:
            from .native_variadic import pack_analysis
            bound={}if callee.class_body is not None else callee.signature.bind(argument_cells,keyword_cells,callee.default_cells,pack_positional=lambda members:pack_analysis(self,callee,members,node)).by_name
        except CallBindingError:raise ClassUnsupported(node)from None
        callee=self.specializations.select(callee,bound,create=True)
        self.activate_frame(caller,node,callee,environment)
        for name, value in bound.items():
            if name in getattr(callee,"erased_context_parameters",()):continue
            if not self.namespace.contribute(callee.arguments[name],value,node,force=True):
                self.contribute(callee.arguments[name], value, node)
        if getattr(callee,'source_generator',None)is None:
            self.namespace.call_effects(caller,callee,environment)
        from .native_source_returns import project_result
        return project_result(self,caller,node,callee,bound)

    def call(self, plan, node, environment):
        from .native_source_generators import guard_call as source_generator_guard_call
        source_generator_guard_call(self,plan,node,environment)
        expanded=self.expanded_calls.analyze(plan,node,environment)
        if expanded is not None:return expanded
        value=self.callable_cells.analyze(plan,node,environment)
        if value is not None:return value
        from .native_frame_references import call_target
        callee=call_target(self,plan,node)
        if callee is not None:
            arguments=[self.expression(plan,value,environment)for value in node.args]
            keywords=[(value.arg,self.expression(plan,value.value,environment))for value in node.keywords]
            return self.bind_call(plan,node,callee,arguments,keywords,environment)
        function = node.func
        if isinstance(function,ast.Name):
            name=self.resolved_name(plan,function)
            current=environment.get(name)
            if (name in CORE_BUILTINS and name in self.global_written_names and self.namespace.owns(plan,function)
                    and (current is None or current.root().tag not in self.INTRINSICS)):
                raise ClassUnsupported(function,f"call name {name!r} has module-owned writes, so its current binding cannot be assumed to be the default builtin; invoking rebound callable values or restoring builtin lookup after deletion is not implemented on this typed frame path",proof="current module/builtin callable identity")
        if (isinstance(function,ast.Name)and self.is_module_plan(plan) and function.id in CORE_BUILTINS
                and function.id in environment and environment[function.id].root().tag in self.INTRINSICS
                and function.id not in getattr(environment,"definite",environment)):
            raise ClassUnsupported(function)
        if (isinstance(function,ast.Name) and not self.is_module_plan(plan)
                and self.resolved_name(plan,function) in plan.declared and self.resolved_name(plan,function) not in environment):
            raise ClassUnsupported(node)
        if (isinstance(function,ast.Name) and function.id in self.BUILTINS
                and self.resolved_name(plan,function) not in environment
                and function.id not in self.classes and function.id not in self.functions
                and not isinstance(self.builtin_identity(plan,function,environment),BuiltinIdentity)):
            raise ClassUnsupported(function)
        self.condition_calls.discard((plan.index,id(node)))
        if (isinstance(function,ast.Name)and self.builtin_identity(plan,function,environment)==BuiltinIdentity("bool")
                and len(node.args)<=1 and not node.keywords):
            for value in node.args:self.condition(plan,value,environment)
            self.condition_calls.add((plan.index,id(node)))
            return self.cell(plan,node,"bool")
        if (isinstance(function,ast.Name) and self.builtin_identity(plan,function,environment)==BuiltinIdentity("map")
                and len(node.args) == 2 and not node.keywords and isinstance(node.args[0],ast.Name)
                and self.builtin_identity(plan,node.args[0],environment)==BuiltinIdentity("int")
                and self.iterators.immediate_integer_map(plan,node,environment)):
            words = self.expression(plan,node.args[1],environment)
            member = self.item(words,node).root()
            if member.tag in {"str","bytes"}:
                return self.cell(plan,node,"map_int",(words,))
            if member.tag is None and not self.final:
                return self.cell(plan,node)
        receiver = None
        if isinstance(function,ast.Attribute):
            receiver=self.callable_cells.receivers.get((plan.index,id(node)))
            if receiver is None:receiver=self.expression(plan,function.value,environment)
            receiver=receiver.root()
        arguments = [self.expression(plan,value,environment) for value in node.args]
        keywords = [(value.arg,self.expression(plan,value.value,environment)) for value in node.keywords]
        if isinstance(function,ast.Name) and(self.resolved_name(plan,function) not in environment
                or self.callable_cells.stable_direct(plan,function,environment)):
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
            identity=self.builtin_identity(plan,function,environment)
            if isinstance(identity,BuiltinIdentity):
                from .native_class_builtins import analyze
                result=analyze(self,plan,node,identity,arguments,keywords,environment)
                if result is not None:return result
        if isinstance(function,ast.Name):
            callable_ = environment.get(self.resolved_name(plan,function))
            if callable_ is None:callable_=self.lexical.read(plan,function,environment)
            if callable_ is not None and callable_.root().tag in {"reader_text","reader_bytes","read_text","read_bytes"}:
                callable_=callable_.root()
                self.remember(plan,function,callable_)
                from .native_class_stdio import analyze as analyze_reader
                return analyze_reader(self,plan,node,callable_.tag,arguments,keywords)
        if receiver is not None:
            from .native_text_join import analyze as analyze_join
            joined=analyze_join(self,plan,node,receiver,arguments,keywords,environment)
            if joined is not None:return joined
            deque=self.deques.analyze_method(plan,node,receiver,arguments,keywords,environment)
            if deque is not None:return deque
            from .native_class_splits import analyze as analyze_split
            split=analyze_split(self,plan,node,receiver,arguments,keywords)
            if split is not None:return split
            from .native_class_text_ops import analyze as analyze_text_operation
            text_operation=analyze_text_operation(self,plan,node,receiver,arguments,keywords,environment)
            if text_operation is not None:return text_operation
            mapped=self.mappings.analyze_method(plan,node,receiver,arguments,keywords,environment)
            if mapped is not None:return mapped
            if receiver.tag == "object":
                owner = self.classes[receiver.args[0]]
                from .native_source_display import guard_direct_method
                guard_direct_method(self,owner,self.resolved_name(plan,function),function)
                method = owner.methods.get(self.resolved_name(plan,function))
                if method is None:
                    raise ClassUnsupported(function)
                return self.bind_call(plan,node,method,[receiver]+arguments,keywords,environment)
            if receiver.tag == "list":
                from .native_sequence_plans import sequence_method,bind_error
                method=sequence_method(shape(receiver),function.attr)
                if method is not None:
                    method=bind_error(method,len(arguments),keywords)
                    if method.error:
                        self.sequence_calls[(plan.index,id(node))]=method
                        return self.cell(plan,node,"none")
                    if method.name=="sort":
                        from .native_class_sorting import analyze_method
                        self.sequence_calls[(plan.index,id(node))]=method
                        return analyze_method(self,plan,node,receiver,arguments,keywords,environment)
                    try:
                        defaults={name:Cell("none"if value is None else"bool"if type(value)is bool else"int")
                                  for name,value in method.defaults}
                        bound=method.signature.bind([receiver]+arguments,keywords,defaults).by_name
                    except CallBindingError:raise ClassUnsupported(node)from None
                    self.sequence_calls[(plan.index,id(node))]=method
                    item=receiver.args[0]
                    if method.name=="append":self.contribute(item,bound["value"],node)
                    elif method.name=="insert"and bound["index"].root().tag in {None,"int","bool","int_bool","union"}:
                        self.contribute(item,bound["value"],node)
                    elif method.name=="extend":self.contribute(item,self.item(bound["iterable"],node),node)
                    elif method.name=="sort"and bound["key"].root().tag not in {None,"none"}:
                        raise ClassUnsupported(node,"the class-aware sequence path only captures None for list.sort key; retaining and invoking a user key callable once per element is not implemented",types=(("key",bound["key"]),),proof="key callable capture and ordered once-per-element evaluation")
                    if method.result=="copy":return self.cell(plan,node,"list",(item,))
                    if method.result=="element":return self.remember(plan,node,item)
                    return self.cell(plan,node,method.result)
            if receiver.tag == "str" and function.attr == "join" and len(arguments) == 1 and not keywords:
                merge(self.item(arguments[0],node),Cell("str"),node)
                return self.cell(plan,node,"str")
            if receiver.tag in {"int","bool","int_bool"} and function.attr in {"bit_length","bit_count"} and not arguments and not keywords:
                return self.cell(plan,node,"int")
            if receiver.tag == "sys" and function.attr in {"setrecursionlimit","getrecursionlimit"} and not keywords:
                if len(arguments) != (1 if function.attr == "setrecursionlimit" else 0):
                    raise ClassUnsupported(node)
                return self.cell(plan,node,"none" if arguments else "int")
            from .native_class_stdio import member as reader_member,analyze as analyze_reader
            intrinsic=reader_member(receiver.tag,function.attr)
            if intrinsic is not None:
                return analyze_reader(self,plan,node,intrinsic,arguments,keywords)
            if receiver.tag is None and not self.final:
                return self.cell(plan,node)
        raise ClassUnsupported(node)

    def attribute_value(self,plan,node,receiver,environment):
        receiver=receiver.root()
        if any(getattr(kind,'_native_exception_class',False)or getattr(kind,'_native_exception_value',False)for kind in alternatives(shape(receiver))):
            raise ClassUnsupported(node,'exception attribute '+repr(node.attr)+' needs exception argument, traceback or descriptor metadata; that exception-object attribute protocol is not implemented',types=(('receiver',shape(receiver)),),proof='exception object attribute and metadata protocol')
        if isinstance(receiver.tag,EmptyType)and not self.final:
            from .native_guard_flow import AnalysisPending
            raise AnalysisPending()
        if hasattr(self,'class_namespaces'):
            value=self.class_namespaces.named_tuples.analyze_attribute(plan,node,receiver,environment)
            if value is not None:return value
        if getattr(shape(receiver),'_native_cmp_key',False):
            raise ClassUnsupported(node,'functools.KeyWrapper attribute '+repr(node.attr)+' requires exposed wrapper-object storage; this native adapter currently supports captured comparison-key factories in sorted and list.sort',types=(('receiver',shape(receiver)),),proof='exposed comparison-key object attributes')
        default=self.mappings.defaultdicts.attribute(plan,node,receiver,environment)
        if default is not None:return default
        deque=self.deques.analyze_attribute(plan,node,receiver)
        if deque is not None:return deque
        from .native_annotations import metadata_access
        metadata_access(node,shape(receiver))
        from .native_finite_attributes import analyze
        finite=analyze(self,plan,node,receiver)
        if finite is not None:return finite
        bound=self.callable_cells.bound_methods.value(plan,node,receiver,environment)
        if bound is not None:return bound
        captured=self.attribute_item(plan,node,receiver,environment)
        if captured is not None:return captured
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

    def attribute_item(self,plan,node,receiver,environment):return None

    def attribute_target(self,plan,node,receiver,value,environment):return False

    def subscript_item(self,plan,node,owner,index,environment):return None

    def item(self, value, node):
        value = value.root()
        deque=self.deques.element(shape(value))
        if deque is not None:return deque
        mapping=self.mappings.views.element(shape(value))
        if mapping is not None:return mapping
        if getattr(value.tag,"_native_class_iterator",False):return self.iterators.item(value.tag)
        if value.tag in {"list","tuple_sequence"}:
            return value.args[0]
        if value.tag == "tuple"or getattr(value.tag,'_native_tuple_record',False):
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
            return self.bind_name(plan,node,value,environment)
        if isinstance(node,(ast.Tuple,ast.List)):
            from .native_class_unpacking import analyze
            if analyze(self,plan,node,value,environment):return
            source = value.root()
            if source.tag == "tuple"or getattr(source.tag,'_native_tuple_record',False):
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
            if self.mappings.defaultdicts.attribute_store(plan,node,owner,value):return
            from .native_annotations import metadata_access
            metadata_access(node,shape(owner))
            if self.attribute_target(plan,node,owner,value,environment):return
            from .native_finite_attributes import analyze
            if analyze(self,plan,node,owner,value=value)is not None:return
            if owner.tag == "object":
                field_ = self.field(self.classes[owner.args[0]],self.resolved_name(plan,node),node,writing=True)
                self.contribute(field_,value,node)
                self.remember(plan,node,field_)
                return
            if owner.tag is None and not self.final:
                return
        if isinstance(node,ast.Subscript) and not isinstance(node.slice,ast.Slice):
            owner = self.expression(plan,node.value,environment).root()
            index=self.expression(plan,node.slice,environment)
            if self.deques.indexes.analyze_store(plan,node,owner,index,value):return
            if self.mappings.analyze_store(plan,node,owner,index,value,environment):return
            if owner.tag == "list":
                self.contribute(owner.args[0],value,node)
                from .native_list_positions import store as positional_store
                positional_store(self,owner,node.slice,value,node)
                self.remember(plan,node,owner.args[0])
                return
            if owner.tag=="union":
                from .native_finite_list_writes import analyze
                if analyze(self,plan,node,owner,index,value):return
                raise ClassUnsupported(node,"indexed assignment through finite owner alternatives needs per-alternative target storage and correlated value projection; that write adapter is not implemented",types=(("receiver",shape(owner)),),proof="per-alternative indexed write storage")
            if owner.tag is None and not self.final:
                return
        raise ClassUnsupported(node)

    def bind_name(self,plan,node,value,environment):
        """Bind an official Name or import-alias node using lexical metadata."""
        if self.lexical.store(plan,node,value,environment):return
        if self.namespace.assign(plan,node,value,environment):return
        self.namespace.prepare_local(plan,node,environment)
        value=self.namespace.local_value(plan,node,value)
        name=self.resolved_name(plan,node)
        if value.root().tag in {"map_int","enumerate"}:raise ClassUnsupported(node)
        if self.is_module_plan(plan)and name in self.global_symbols:raise ClassUnsupported(node)
        environment[name]=value
        environment.definite.add(name)
        self.canonical_local(plan,name,value)
        self.remember(plan,node,value)

    def import_statement(self,plan,node,environment):
        from .native_class_stdio import import_statement
        return import_statement(self,plan,node,environment)

    def join(self, left, right, node, role="join"):
        if left is None:
            return right
        if right is None:
            return left
        result = Environment(left,definite=left.definite&right.definite)
        for name,value in right.items():
            if name in result:
                joined=self.namespace.join_values(result[name],value,node,name,role)
                result[name]=merge(result[name],value,node)if joined is None else joined
            else:
                result[name] = value
        return result

    @staticmethod
    def replace_environment(destination,source):
        destination.clear()
        destination.update(source)
        if hasattr(destination,"definite"):destination.definite=set(source.definite)

    def block(self, plan, statements, environment):
        environment = Environment(environment)
        for node in statements:
            if environment is None:
                break
            if self.final and self.reached_statements is not None:
                self.reached_statements.add((plan.index,id(node)))
            if isinstance(node,(ast.Import,ast.ImportFrom))and self.import_statement(plan,node,environment):
                continue
            if isinstance(node,(ast.ClassDef,ast.FunctionDef)):
                if self.lexical.define(plan,node,environment):
                    self.namespace.define(plan,node,environment)
                    continue
                if not self.is_module_plan(plan) and (plan.class_body is None or not isinstance(node,(ast.FunctionDef,ast.ClassDef))):
                    raise ClassUnsupported(node)
                expected=(self.classes.get(self.definition_name(node))if isinstance(node,ast.ClassDef)else
                          plan.class_body.methods.get(self.resolved_name(plan,node))if plan.class_body is not None else self.functions.definitions.get(node))
                if expected is None or expected.node is not node:
                    raise ClassUnsupported(node)
                registry=getattr(self,"class_namespaces",None)
                if registry is not None:registry.prepare_definition(plan,node,environment)
                self.namespace.define(plan,node,environment)
                if registry is not None:registry.definition_event(plan,node,environment)
                if self.is_module_plan(plan):plan.visible_definitions.add(self.definition_name(node))
                continue
            if isinstance(node,ast.Import):
                if not self.is_module_plan(plan):
                    raise ClassUnsupported(node)
                self.namespace.import_event(plan,node,environment)
                continue
            from .native_annotations import future_directive
            if isinstance(node,(ast.Pass,ast.Global,ast.Nonlocal))or future_directive(node):
                continue
            if isinstance(node,ast.Expr):
                self.expression(plan,node.value,environment)
                from .native_exit import never_returns
                if never_returns(self,plan,node.value):
                    self.native_abrupt_calls_used=True
                    environment=None
            elif isinstance(node,ast.Assign):
                from .native_annotations import metadata_target
                for target in node.targets:metadata_target(self,plan,target,environment)
                from .native_frame_references import alias_assignment
                if alias_assignment(self,plan,node):continue
                if (isinstance(node.value,ast.Call) and isinstance(node.value.func,ast.Name)
                        and self.builtin_identity(plan,node.value.func,environment)==BuiltinIdentity("map")
                        and len(node.value.args)==2 and not node.value.keywords
                        and isinstance(node.value.args[0],ast.Name)
                        and self.builtin_identity(plan,node.value.args[0],environment)==BuiltinIdentity("int")
                        and len(node.targets)==1 and isinstance(node.targets[0],(ast.Tuple,ast.List))
                        and not any(isinstance(item,ast.Starred)for item in node.targets[0].elts)):
                    words = self.expression(plan,node.value.args[1],environment)
                    member = self.item(words,node.value).root()
                    if member.tag in {"str","bytes"}:
                        value = self.cell(plan,node.value,"map_int",(words,))
                    elif member.tag is None and not self.final:
                        value = self.cell(plan,node.value)
                    else:
                        value = self.expression(plan,node.value,environment)
                else:
                    value = self.expression(plan,node.value,environment)
                for target in node.targets:
                    self.target(plan,target,value,environment)
            elif isinstance(node,ast.AnnAssign):
                from .native_annotations import metadata_target
                if node.value is not None:
                    metadata_target(self,plan,node.target,environment)
                    self.target(plan,node.target,self.expression(plan,node.value,environment),environment)
                else:
                    from .native_annotations import target_inputs
                    for expression in target_inputs(node.target):self.expression(plan,expression,environment)
            elif isinstance(node,ast.Assert):
                from .native_assertions import analyze
                analyze(self,plan,node,environment)
            elif isinstance(node,ast.Raise):
                self.exceptions.analyze_raise(plan,node,environment)
                environment=None
            elif isinstance(node,ast.AugAssign):
                left = self.expression(plan,node.target,environment)
                self.augmented[(plan.index,id(node))] = left
                right = self.expression(plan,node.value,environment)
                value = self.binary(plan,node,node.op,left,right,environment=environment)
                if not self.deques.indexes.captured_store(plan,node.target,value):
                    self.target(plan,node.target,value,environment)
            elif isinstance(node,ast.Delete):
                from .native_annotations import metadata_target
                from .native_class_deletion import analyze
                for target in node.targets:
                    metadata_target(self,plan,target,environment)
                    if not analyze(self,plan,target,environment):
                        if not self.lexical.delete(plan,target,environment):self.namespace.delete(plan,target,environment)
            elif isinstance(node,ast.With):
                environment=self.context_managers.analyze(plan,node,environment)
            elif isinstance(node,ast.If):
                self.condition(plan,node.test,environment)
                from .native_guard_flow import branches
                narrowed=branches(self,plan,node.test,environment)
                yes,no=(environment,environment)if narrowed is None else narrowed
                environment = self.join(None if yes is None else self.block(plan,node.body,yes),None if no is None else self.block(plan,node.orelse,no),node)
            elif isinstance(node,(ast.For,ast.While)):
                from .native_loop_else import condition as loop_condition
                if node.orelse:self.loop_reachability_used=True
                known=loop_condition(self,node)
                if known is not None:self.loop_reachability_used=True
                if known is False:
                    self.condition(plan,node.test,environment)
                    environment=self.block(plan,node.orelse,environment)
                    continue
                value=None
                if isinstance(node,ast.For):
                    value = self.expression(plan,node.iter,environment)
                    from .native_class_iterators import tuple_cursor_required
                    if self.iterators.needs_source_cursor(shape(value)) or tuple_cursor_required(shape(value)):
                        value=Cell(self.iterators.source(plan,node,value,environment=environment))
                    elif value.root().tag=='enumerate'and self.iterators.needs_source_cursor(shape(value.root().args[0])):
                        self.iterators.source(plan,node,value.root().args[0],environment=environment)
                start=Environment(environment)
                key=plan.index,id(node)
                from .native_loop_flow import header as loop_header
                header=loop_header(self,start,self.loop_feedback.get(key),node)
                if isinstance(node,ast.For):
                    self.target(plan,node.target,self.iterators.demand(plan,node,value,header),header)
                else:
                    self.condition(plan,node.test,header)
                    start=Environment(header)
                self.loop_depth += 1
                self.loop_edges.append([])
                self.loop_continues.append([])
                body = self.block(plan,node.body,header)
                continues=self.loop_continues.pop()
                edges = self.loop_edges.pop()
                self.loop_depth -= 1
                feedback=body
                for edge in continues:feedback=self.join(feedback,edge,node,"loop_feedback")
                if feedback is not None:self.loop_feedback[key]=Environment(feedback)
                environment = None if known is True else self.join(start,feedback,node,"loop_exit")
                if node.orelse and environment is not None:
                    environment = self.block(plan,node.orelse,environment)
                for edge in edges:
                    environment = self.join(environment,edge,node,"loop_exit")
            elif isinstance(node,ast.Return):
                if self.is_module_plan(plan):
                    raise ClassUnsupported(node)
                value = Cell("none") if node.value is None else self.expression(plan,node.value,environment)
                if getattr(plan,'source_generator',None)is not None:
                    from .native_source_generators import analyze_return
                    analyze_return(self,plan,node,value)
                else:self.contribute(plan.result,value,node)
                environment = None
            elif isinstance(node,(ast.Break,ast.Continue)):
                if not self.loop_depth:
                    raise ClassUnsupported(node)
                if isinstance(node,ast.Continue):self.loop_continues[-1].append(Environment(environment))
                else:self.loop_edges[-1].append(Environment(environment))
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
        self.loop_field_caches = []
        self.list_access_regions = []
        self.list_access_tails = {}
        self.slots = {}
        self.reference_slots = {}
        from .native_primitive_parameter_places import prepare as primitive_parameters
        self.readonly_owned_parameters={}
        self.primitive_parameters=primitive_parameters(self)
        if model.integer == "bigint":
            from .native_bigint import BigIntGenerator
            self.numeric = BigIntGenerator(function=SimpleNamespace(node=SimpleNamespace(name=plan.scope)))
        else:
            from .native_scalar import ScalarGenerator
            self.numeric = ScalarGenerator(64 if model.integer == "i64" else 128,
                                           function=SimpleNamespace(node=SimpleNamespace(name=plan.scope)))
        self.numeric.string_mode=model.string_mode
        from .native_owned_local_lists import prepare as prepare_owned_lists
        self.owned_local_lists=prepare_owned_lists(self)
        from .native_owned_matrix_places import prepare as prepare_matrices
        self.owned_matrices=prepare_matrices(self,self.owned_local_lists)
        self.owned_local_lists={name:local for name,local in self.owned_local_lists.items()if name not in self.owned_matrices}
        from .native_record_places import prepare as prepare_record_places
        self.record_places=prepare_record_places(self)
        self.owned_local_lists={name:local for name,local in self.owned_local_lists.items()if name not in self.record_places}
        for name, values in plan.locals.items():
            if model.is_module_plan(plan) and name in model.namespace.active:continue
            shared=model.namespace.local_kind(plan,name)
            if shared is not None:
                self.slot(name,shared)
                continue
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
        return render_type(kind,self.rust_leaf)

    def rust_leaf(self,value,recurse):
        if getattr(value,'_native_exception_class',False):return 'ClassExceptionClass'+value.name
        if getattr(value,'_native_exception_value',False):return 'Rc<ClassExceptionValue'+str(value.record.index)+'>'
        if getattr(value,"_native_builtin_singleton",False):return "NativeNotImplemented"
        if getattr(value,'_native_cmp_key',False):return 'Rc<NativeCmpKey_'+str(value.record.index)+'>'
        if getattr(value,"_native_erased_argument",False):return "()"
        if getattr(value,'_native_class_deque',False):return self.model.deques.rust_type(self,value)
        if getattr(value,'_native_mapping_view',False):return self.model.mappings.views.rust_type(value)
        if getattr(value,"_native_class_mapping",False):return self.model.mappings.rust_type(value)
        if getattr(value,"_native_class_generator",False):return f"ClassIterator_{value.record.outer.index}"
        if getattr(value,"_native_class_iterator",False):return f"ClassIterator_{value.index}"
        if getattr(value,"_native_function_reference",False):
            from .native_callable_carriers import rust_type
            return rust_type(self.model,value)
        if getattr(value,"_native_namespace_view",False):return "ClassGlobalsView"
        if isinstance(value,InstanceType):return f"ClassHandle_{self.model.classes[value.name].index}"
        if isinstance(value,ListType):return f"ClassList<{recurse(value.element)}>"
        if value=="range":return "ClassRange"
        if isinstance(value,str)and value in self.model.INTRINSICS:return '()'
        if isinstance(value,StreamType):
            raise ClassUnsupported(self.plan.node)
        return None

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
        error="NameError"if self.model.is_module_plan(self.plan) else"UnboundLocalError"
        message=(f"name '{self.model.display_name(name)}' is not defined"if error=="NameError"else
                 f"cannot access local variable '{self.model.display_name(name)}' where it is not associated with a value")
        result=f"if {slot}{{Ok(())}}else{{Err({_string(error+': '+message)}.to_owned())}}"
        return Expression(self.at(result,node),kind)

    def at(self, result, node):
        return f"native_at({result},{node.lineno},{self.location_code()})?"

    def location_code(self):return _string(getattr(self,'logical_scope',self.plan.scope))

    def prepare_call_context(self,callee,receiver,constructor,defining_module=None,*,node=None):return ""

    def constructor_context_arguments(self,constructor,defining_class):return []

    def emit_import(self,node):
        from .native_class_stdio import emit_import
        return emit_import(self,node)

    def unsupported(self, node):
        raise ClassUnsupported(node)

    def coerce(self, value, kind, node):
        from .native_types import tuple_nominal_compatible
        if getattr(kind,"_native_erased_argument",False):return "{let _="+value.code+";()}"
        if value.kind == kind:return value.code
        if isinstance(value.kind,EmptyType):return f"native_empty({value.code})"
        if getattr(value.kind,"_native_function_reference",False)and getattr(kind,"_native_function_reference",False):
            from .native_callable_carriers import convert
            return convert(self,node,value.kind,kind,value.code)
        if union_kind(value.kind):
            return project(value.kind,value.code,
                lambda source,code:self.coerce(Expression(f"({code}).clone()",source),kind,node))
        if union_kind(kind):
            choices=alternatives(kind)
            chosen=value.kind if value.kind in choices else next((option for option in choices
                if option=="int_bool"and value.kind in {"int","bool"}
                or getattr(option,"_native_function_reference",False)and getattr(value.kind,"_native_function_reference",False)and set(value.kind.targets)<=set(option.targets)
                or isinstance(option,TupleType)and isinstance(value.kind,TupleType)
                    and len(option.fields)==len(value.kind.fields)and tuple_nominal_compatible(option,value.kind)),None)
            if chosen is None:raise ClassUnsupported(node)
            return construct(kind,chosen,self.coerce(value,chosen,node))
        if kind == "int_bool"and value.kind in {"int","bool"}:
            return f"NativeScalar::{'Int' if value.kind == 'int' else 'Bool'}({value.code})"
        if kind == "int"and value.kind in {"bool","int_bool"}:return self.number(value)
        if isinstance(kind,TupleType)and isinstance(value.kind,TupleType)and len(kind.fields)==len(value.kind.fields):
            if not tuple_nominal_compatible(kind,value.kind):
                raise ClassUnsupported(node,'value conversion would erase or replace the actual NamedTuple class identity; a semantic tuple-construction adapter is required',proof='preserved nominal tuple identity')
            temporary=self.fresh()
            values=[self.coerce(Expression(f"{temporary}.{i}.clone()",old),new,node)
                    for i,(old,new)in enumerate(zip(value.kind.fields,kind.fields))]
            return f"{{let {temporary}={value.code};"+tuple_code(values)+"}"
        raise ClassUnsupported(node)

    def encoded(self, code, raw_kind, wanted, node, constant=None):
        return Expression(self.coerce(Expression(code,raw_kind,constant),wanted,node),wanted,constant)

    def capture(self, value):
        name = self.fresh()
        annotation=":Vec<u8>"if value.kind=="bytes"else""
        return f"let {name}{annotation}={value.code};",Expression(name,value.kind,value.constant)

    def scalar(self, value):
        return value

    def number(self, value):
        return self.numeric.number(self.scalar(value))

    def literal(self, value):
        return self.numeric.literal(value)

    def condition(self,node,environment=None):
        from .native_conditions import lower
        result=lower(self,node)
        return Expression(result.code,"bool",result.constant)

    def condition_leaf(self,node):
        value=self.expression(node)
        owner,result=self.fresh(),self.fresh()
        captured=Expression(owner,value.kind,value.constant)
        truth=self.truth(captured,node)
        # Truth-only use supplies no result-type context for an empty generic
        # container. Retain its solved physical type and end borrow guards
        # before the captured Rc owner leaves this block.
        setup=f"let {owner}:{self.rust_type(value.kind)}={value.code};"
        return Expression("{"+setup+f"let {result}={truth};{result}"+"}","bool")

    def truth(self, value, node=None):
        if getattr(value.kind,'_native_exception_class',False)or getattr(value.kind,'_native_exception_value',False):return 'true'
        if getattr(value.kind,"_native_builtin_singleton",False):
            from .native_builtin_singletons import truth
            return truth(self,value,node)
        if getattr(value.kind,'_native_class_deque',False):return self.model.deques.truth(self,value)
        if getattr(value.kind,'_native_mapping_view',False):return self.model.mappings.views.truth(self,value)
        if isinstance(value.kind,EmptyType):return f"native_empty::<bool>({value.code})"
        if union_kind(value.kind):return project(value.kind,value.code,
            lambda kind,code:self.truth(Expression(code,kind),node))
        tag = domain(value.kind)
        if tag in {"dict","set"}:return self.model.mappings.truth(self,value)
        if tag in {"int","bool","int_bool"}:
            return self.numeric.truth(self.scalar(value))
        if tag in {"function","iterator","cmp_key"}:return "true"
        if tag=="globals_dict":return "true"
        if tag in {"str","bytes","tuple_sequence"}:
            return f"!({value.code}).is_empty()"
        if tag == "float":
            return f"({value.code})!=0.0"
        if tag == "list":
            result=self.fresh()
            return f"{{let {result}=!({value.code}).borrow().is_empty();{result}}}"
        if tag == "none":
            return "false"
        if tag == "object":
            owner=self.model.classes[value.kind.name]
            methods=sorted({"__bool__","__len__"}.intersection(owner.methods))
            if owner.node.bases or methods:
                required="/".join(methods)if methods else"inherited __bool__/__len__ slots"
                raise ClassUnsupported(None,f"class {owner.node.name!r} requires {required} truth-value dispatch; this native path only implements default object truth and does not yet invoke overridden/inherited truth methods",operation=f"truth-value test of class {owner.node.name!r}",types=(("value",value.kind),),proof="Python special-method truth dispatch")
            return "true"
        if tag == "tuple":
            return str(bool(value.kind.fields)).lower()
        raise ClassUnsupported(self.plan.node)

    def show(self, value, node, representation=False):
        from .native_source_display import show as source_show
        source=source_show(self,value,node,representation)
        if source is not None:return source
        if getattr(value.kind,'_native_exception_class',False)or getattr(value.kind,'_native_exception_value',False):
            from .native_exception_values import show
            return show(self,value,node,representation)
        if getattr(value.kind,'_native_named_tuple',False):
            from .native_named_tuples import show
            return show(self,value,node)
        if getattr(value.kind,"_native_builtin_singleton",False):return _string(value.kind.name)+".to_owned()"
        if getattr(value.kind,'_native_class_deque',False):return self.model.deques.show(self,value,node)
        if getattr(value.kind,'_native_mapping_view',False):return self.model.mappings.views.show(self,value,node)
        if isinstance(value.kind,EmptyType):return f"native_empty::<String>({value.code})"
        if union_kind(value.kind):return project(value.kind,value.code,
            lambda kind,code:self.show(Expression(code,kind),node,representation))
        if isinstance(value.kind,TupleSequenceType):
            from .native_variadic import show
            return show(self,value,node)
        if getattr(value.kind,"_native_class_mapping",False):return self.model.mappings.show(self,value,node)
        if isinstance(value.kind,ListType):
            item=self.fresh()
            rendered=self.show(Expression(f"(*{item}).clone()",value.kind.element),node,True)
            return f'format!("[{{}}]",({value.code}).borrow().iter().map(|{item}|{rendered}).collect::<Vec<_>>().join(", "))'
        tag = domain(value.kind)
        if tag == "str" and representation:
            self.model.string_repr_required = True
        if tag == "tuple":
            fields = [self.show(Expression(f"{value.code}.{i}.clone()",kind),node,True)
                      for i,kind in enumerate(value.kind.fields)]
            return "class_tuple_text(&[" + ",".join(fields) + "])"
        if tag=="iterator"and hasattr(value.kind.record,"tool"):
            return 'format!("<itertools.'+value.kind.record.tool+' object at 0x{:x}>",Rc::as_ptr(&('+value.code+'))as usize)'
        if tag=="function":
            from .native_callable_display import emit as show_callable
            return show_callable(self,value,node)
        if tag=="globals_dict":
            raise ClassUnsupported(node,"displaying this globals dictionary needs value lookup and ordered dictionary repr; the live namespace view currently implements binding membership, length and identity",proof="module namespace value/iteration protocol")
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
        result={name:self.literal_value(value,shape(callee.default_cells[name]),callee.defaults[name])
                for name,value in callee.default_literals.items()}
        from .native_class_globals import default_read
        if isinstance(callee.node,ast.Lambda):default_read=lambda emitter,plan,name:self.model.lambda_cells.default_read(emitter,plan,name)
        result.update({name:default_read(self,callee,name)for name in callee.defaults if name not in result})
        return result

    def expression(self, node):
        from .native_source_state import total_read
        state_value=total_read(self,node)
        if state_value is not None:return state_value
        from .native_owned_object_places import expression as owned_object_expression
        owned_object=owned_object_expression(self,node)
        if owned_object is not None:return owned_object
        from .native_owned_matrix_places import read as matrix_read
        matrix=matrix_read(self,node)
        if matrix is not None:return matrix
        from .native_record_places import read as record_read
        record=record_read(self,node)
        if record is not None:return record
        from .native_owned_local_lists import read as owned_read
        owned=owned_read(self,node)
        if owned is not None:return owned
        from .native_owned_class_lists import expression as owned_field_expression
        owned_field=owned_field_expression(self,node)
        if owned_field is not None:return owned_field
        from .native_namespace_read_places import read as namespace_read
        namespace_value=namespace_read(self,node)
        if namespace_value is not None:return namespace_value
        from .native_list_end_indices import class_read
        endpoint=class_read(self,node)
        if endpoint is not None:return endpoint
        from .native_list_access_regions import read as region_read
        optimized=region_read(self,node)
        if optimized is not None:return optimized
        from .native_tuple_projection import read as tuple_projection
        projected=tuple_projection(self,node)
        if projected is not None:return projected
        from .native_scalar_attribute_projection import read as scalar_attribute
        projected=scalar_attribute(self,node)
        if projected is not None:return projected
        exception=self.model.exceptions.read(self,node)
        if exception is not None:return exception
        from .native_builtin_singletons import read as read_singleton
        singleton=read_singleton(self,node)
        if singleton is not None:return singleton
        wanted = self.kind(node)
        if isinstance(node,ast.JoinedStr):
            from .native_formatting import emit_joined
            return emit_joined(self,node)
        if isinstance(node,ast.GeneratorExp):return self.model.generators.construct(self,node)
        if isinstance(node,ast.Lambda):return self.model.lambda_cells.emit_value(self,node)
        if isinstance(node,ast.ListComp):
            from .native_class_comprehensions import emit
            return emit(self,node)
        if isinstance(node,ast.Constant):
            return self.literal_value(node.value,wanted,node)
        if isinstance(node,ast.Name):
            from .native_scalar_data_parameters import read as data_parameter_read
            data_parameter=data_parameter_read(self,node)
            if data_parameter is not None:return data_parameter
            lexical=self.model.lexical.emit_function(self,node,wanted)
            if lexical is None:lexical=self.model.lexical.emit_read(self,node,wanted)
            if lexical is not None:return lexical
            builtin=self.model.callable_cells.read_emission(self,node)
            if builtin is not None:return builtin
            from .native_class_comprehensions import read_binding
            binding=read_binding(self,node,wanted)
            if binding is not None:return binding
            from .native_class_globals import read
            binding=read(self,node,wanted)
            if binding is not None:return binding
            from .native_class_globals import local_read
            binding=local_read(self,node,wanted)
            if binding is not None:return binding
            from .native_primitive_parameter_places import read as primitive_parameter
            direct=primitive_parameter(self,node)
            if direct is not None:return direct
            name = self.model.resolved_name(self.plan,node)
            if domain(wanted) in self.model.INTRINSICS:
                return self.reference_read(name,wanted,node)
            if node.id == "__name__" and name not in self.plan.locals:
                return Expression('NativeText::from("__main__")','str')
            slot = self.slot(name,wanted)
            kind = "NameError" if self.model.is_module_plan(self.plan) else "UnboundLocalError"
            message = (f"name '{self.model.display_name(name)}' is not defined" if kind == "NameError" else
                       f"cannot access local variable '{self.model.display_name(name)}' where it is not associated with a value")
            result = f"{slot}.clone().ok_or_else(||{_string(kind+': '+message)}.to_owned())"
            return Expression(self.at(result,node),wanted)
        if isinstance(node,ast.Tuple):
            raw=shape(self.model.constructors[(self.plan.index,id(node))])
            values=[self.coerce(self.expression(value),kind,value)for value,kind in zip(node.elts,raw.fields)]
            return self.encoded(tuple_code(values),raw,wanted,node)
        if isinstance(node,ast.List):
            if not node.elts:
                return Expression(f"class_list(Vec::<{self.rust_type(wanted.element)}>::new())",wanted)
            values = [self.coerce(self.expression(value),wanted.element,value) for value in node.elts]
            return Expression("class_list(vec!["+",".join(values)+"])",wanted)
        if isinstance(node,(ast.Dict,ast.Set,ast.DictComp,ast.SetComp)):
            return self.model.mappings.emit_expression(self,node)
        if isinstance(node,ast.Attribute):
            from .native_finite_attributes import selected,emit
            if selected(self.model,self.plan,node):
                before,receiver=self.capture(self.expression(node.value))
                value=emit(self,node,receiver,wanted)
                return Expression('{'+before+value.code+'}',wanted)
            if node.attr=='default_factory':
                from .native_class_defaultdicts import is_default
                if all(is_default(kind)for kind in alternatives(self.kind(node.value))):
                    before,owner=self.capture(self.expression(node.value))
                    return Expression('{'+before+self.model.mappings.defaultdicts.emit_attribute(self,node,owner,wanted)+'}',wanted)
            bound=self.model.callable_cells.bound_methods.read(self,node)
            if bound is not None:return bound
            if domain(wanted) in self.model.INTRINSICS:
                receiver=self.expression(node.value)
                return Expression("{let _="+receiver.code+";()}",wanted)
            receiver = self.expression(node.value)
            if domain(receiver.kind)=="deque"or union_kind(receiver.kind)and any(domain(part)=="deque"for part in alternatives(receiver.kind)):
                return self.model.deques.emit_attribute(self,node,receiver,wanted)
            if domain(receiver.kind) != "object":
                raise ClassUnsupported(node)
            owner = self.model.classes[receiver.kind.name]
            index = list(owner.fields).index(self.model.resolved_name(self.plan,node))
            code=self.at(f"class_get_{owner.index}_{index}(&({receiver.code}))",node)
            from .native_class_loop_fields import read
            return Expression(read(self,node,code,wanted),wanted)
        if isinstance(node,ast.Subscript):
            if isinstance(node.slice,ast.Slice):
                from .native_frame_slices import emit
                return emit(self,node,wanted)
            setup,owner = self.capture(self.expression(node.value))
            index_setup,index = self.capture(self.expression(node.slice))
            if getattr(owner.kind,"_native_class_mapping",False)or union_kind(owner.kind)and any(getattr(part,"_native_class_mapping",False)for part in alternatives(owner.kind)):
                value=self.model.mappings.emit_get(self,node,owner,index,wanted)
                return Expression('{'+setup+index_setup+value.code+'}',wanted)
            if all(domain(kind)=="deque"for kind in alternatives(owner.kind)):
                value=self.model.deques.indexes.emit(self,node,owner,index,wanted)
                return Expression("{"+setup+index_setup+value.code+"}",wanted)
            from .native_union_sequences import emit_subscript
            indexed=emit_subscript(self,node,owner,index,wanted)
            if indexed is not None:return Expression("{"+setup+index_setup+indexed.code+"}",wanted)
            tag = domain(owner.kind)
            if tag == "list":
                code = self.at(f"class_list_get(&{owner.code},&({self.number(index)}))",node)
                from .native_list_positions import project_element
                code=project_element(self,code,owner.kind.element,wanted,node).code
            elif tag == "tuple_sequence":
                offset=self.at(f'class_index(&({self.number(index)}),{owner.code}.len()).map_err(|_|"IndexError: tuple index out of range".to_owned())',node)
                code=f"{owner.code}.as_slice()[{offset}].clone()"
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
            from .native_integer_windows import frame as integer_window
            window=integer_window(self,node)
            if window is not None:return window
            setup,left = self.capture(self.expression(node.left))
            more,right = self.capture(self.expression(node.right))
            result = self.binary(node.op,left,right,node,wanted)
            return Expression(f"{{{setup}{more}{result.code}}}",wanted,result.constant)
        if isinstance(node,ast.UnaryOp):
            if isinstance(node.op,ast.Not):return self.condition(node)
            setup,value = self.capture(self.expression(node.operand))
            result=self.model.operators.emit_unary(self,node,node.op,value,wanted)
            if result is None:result=self.unary_builtin(node.op,value,node,wanted)
            return Expression("{"+setup+result.code+"}",wanted,result.constant)
        if isinstance(node,ast.IfExp):
            setup,test = self.capture(self.condition(node.test))
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
                return "{"+setup+"if "+self.truth(value,values[0])+"{"+yes+"}else{"+no+"}}"
            return Expression(combine(node.values),wanted)
        if isinstance(node,ast.Compare):
            from .native_class_binding_contexts import comparison as class_binding_comparison
            class_binding=class_binding_comparison(self,node,wanted)
            if class_binding is not None:return class_binding
            custom=self.model.operators.emit_compare_expression(self,node,wanted)
            if custom is not None:return custom
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
        if isinstance(node,ast.NamedExpr):
            setup,value=self.capture(self.expression(node.value))
            saved=Expression(value.code+".clone()",value.kind,value.constant)
            code="{"+setup+self.assign(node.target,saved)+value.code+"}"
            return self.encoded(code,value.kind,wanted,node,value.constant)
        raise ClassUnsupported(node)

    def unary_builtin(self,operator,value,node,wanted):
        if value.kind == 'float':
            raw = Expression(("-"if isinstance(operator,ast.USub)else"")+value.code,'float')
        else:
            number = self.number(value)
            if isinstance(operator,ast.UAdd):
                code = number
            elif isinstance(operator,ast.USub):
                code = f"({number}).neg()"if self.model.integer=="bigint"else f"({number}).wrapping_neg()"
            else:
                code = f"({number}).invert()"if self.model.integer=="bigint"else f"!({number})"
            constant = None
            if value.constant is not None:
                constant = self.numeric.normalize(-int(value.constant) if isinstance(operator,ast.USub) else
                                                  ~int(value.constant) if isinstance(operator,ast.Invert) else int(value.constant))
            raw = Expression(code,'int',constant)
        return Expression(self.coerce(raw,wanted,node),wanted,raw.constant)

    def binary(self, operator, left, right, node, wanted, *, identity=None):
        result=self.model.operators.emit_binary(self,operator,left,right,node,wanted,identity=identity)
        if result is not None:return result
        return self.binary_builtin(operator,left,right,node,wanted)

    def binary_builtin(self, operator, left, right, node, wanted):
        from .native_integral_powers import frame as integral_power
        power=integral_power(self,operator,left,right,node,wanted)
        if power is not None:return power
        from .native_constant_divisors import frame as constant_divisor
        divided=constant_divisor(self,operator,left,right,node,wanted)
        if divided is not None:return divided
        from .native_primitive_ops import emit,classify
        primitive_tags={"int","bool","int_bool","float","str","bytes","none","function","globals_dict","range","list","tuple"}
        if (union_kind(left.kind)or union_kind(right.kind)or domain(left.kind)in primitive_tags
                and domain(right.kind)in primitive_tags
                and classify(operator,left.kind,right.kind,self.model.integer).error is not None):
            return emit(self,operator,left,right,node,wanted)
        a,b = domain(left.kind),domain(right.kind)
        if a==b=="list" and isinstance(operator,ast.Add):
            return self.encoded(f"class_list_concat(&{left.code},&{right.code})",left.kind,wanted,node)
        if "list" in {a,b} and isinstance(operator,ast.Mult):
            values,count = (left,right)if a=="list"else(right,left)
            return self.encoded(self.at(f"class_list_repeat(&{values.code},&({self.number(count)}))",node),values.kind,wanted,node)
        if a==b=="str" and isinstance(operator,ast.Add):
            return self.encoded(self.at(f"class_string_add({left.code},&{right.code})",node),'str',wanted,node)
        if "str" in {a,b} and isinstance(operator,ast.Mult):
            value,count = (left,right)if a=="str"else(right,left)
            return self.encoded("NativeText::from("+self.at(f"class_string_repeat(&{value.code},&({self.number(count)}))",node)+")",'str',wanted,node)
        result = self.numeric.binary(operator,self.scalar(left),self.scalar(right),node)
        raw = result.kind
        return self.encoded(result.code,raw,wanted,node,result.constant)

    def comparison(self, operator, left, right, node):
        self.model.operators.implicit_comparison_guard(self,operator,left,right,node)
        return self.comparison_builtin(operator,left,right,node)

    def comparison_builtin(self, operator, left, right, node):
        if getattr(left.kind,"_native_builtin_singleton",False)and left.kind==right.kind and isinstance(operator,(ast.Is,ast.IsNot,ast.Eq,ast.NotEq)):
            return "false"if isinstance(operator,(ast.IsNot,ast.NotEq))else"true"
        if union_kind(left.kind):return project(left.kind,left.code,
            lambda kind,code:self.comparison(operator,Expression(f"({code}).clone()",kind),right,node))
        if union_kind(right.kind):return project(right.kind,right.code,
            lambda kind,code:self.comparison(operator,left,Expression(f"({code}).clone()",kind),node))
        from .native_exception_values import comparison as exception_comparison
        exception=exception_comparison(operator,left,right)
        if exception is not None:return exception
        if isinstance(operator,(ast.Is,ast.IsNot))and domain(left.kind)==domain(right.kind)=="deque":
            code="Rc::ptr_eq(&"+left.code+",&"+right.code+")"if left.kind==right.kind else"false"
            return "!("+code+")"if isinstance(operator,ast.IsNot)else code
        mapped=self.model.mappings.comparison(self,operator,left,right,node)
        if mapped is not None:return mapped
        from .native_globals_view import comparison as globals_comparison
        observed=globals_comparison(self,operator,left,right,node)
        if observed is not None:return observed
        from .native_variadic import comparison as tuple_sequence_comparison
        sequence_result=tuple_sequence_comparison(self,operator,left,right,node)
        if sequence_result is not None:return sequence_result
        a,b = domain(left.kind),domain(right.kind)
        if isinstance(operator,(ast.Is,ast.IsNot)):
            if a==b=="function":
                from .native_callable_carriers import comparison
                code=comparison(self,left,right,identity=True)
            elif a==b and a in {"object","list","iterator","dict_view","cmp_key"}:
                from .native_value_classes import identity_equal
                code = (identity_equal(self.model,left.kind,left.code,right.code)if left.kind==right.kind else"false")
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
        from .native_class_storage import comparison as shared_comparison
        shared_result=shared_comparison(self,operator,left,right,node)
        if shared_result is not None:return shared_result
        if a==b=="function"and isinstance(operator,(ast.Eq,ast.NotEq)):
            from .native_callable_carriers import comparison
            code=comparison(self,left,right)
            return '!('+code+')'if isinstance(operator,ast.NotEq)else code
        if isinstance(operator,(ast.In,ast.NotIn))and isinstance(right.kind,TupleType):
            from .native_tuples import membership
            return membership(self,left,right,operator,node)
        if not isinstance(operator,(ast.In,ast.NotIn))and(isinstance(left.kind,TupleType)or isinstance(right.kind,TupleType)):
            from .native_tuples import tuple_compare,_scalar
            if not _scalar(left.kind)or not _scalar(right.kind):raise ClassUnsupported(node)
            return tuple_compare(self,left,right,operator,node)
        if isinstance(operator,(ast.Eq,ast.NotEq)) and (a=="none"or b=="none"):
            code = str(a==b).lower()
            return f"!({code})"if isinstance(operator,ast.NotEq)else code
        if a==b=="object"and isinstance(operator,(ast.Eq,ast.NotEq)):
            from .native_value_classes import identity_equal
            code = identity_equal(self.model,left.kind,left.code,right.code)if left.kind==right.kind else"false"
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
        if a==b=="float"and type(operator)in symbols:
            return f"({left.code}){symbols[type(operator)]}({right.code})"
        if a==b and a in {"str","bytes"}and type(operator)in symbols:
            return f"{left.code}{symbols[type(operator)]}{right.code}"
        if self.model.integer=="bigint"and a in numeric|{"float"}and b in numeric|{"float"}:
            from .native_comparisons import real_comparison
            compared=real_comparison(self.numeric,self.scalar(left),self.scalar(right),operator,node)
            if compared is not None:return compared
        if self.model.integer!="bigint"and a in numeric|{"float"}and b in numeric|{"float"}:
            temporary=SimpleNamespace(ops=[operator])
            return self.numeric.compare(temporary,[self.scalar(left),self.scalar(right)]).code
        if isinstance(operator,(ast.Eq,ast.NotEq))and a!=b:
            return str(isinstance(operator,ast.NotEq)).lower()
        if isinstance(operator,(ast.Lt,ast.LtE,ast.Gt,ast.GtE))and'object'in {a,b}:
            sealed={'object','int','bool','int_bool','float','str','bytes','none','function','list','tuple','tuple_sequence','range','globals_dict','dict','set','dict_view'}
            if a in sealed and b in sealed:
                from .native_class_builtins import _type_name
                symbol=symbols[type(operator)]
                message=_string(f"TypeError: '{symbol}' not supported between instances of '{{}}' and '{{}}'")
                return self.at('Err::<bool,String>(format!('+message+','+_type_name(self,left,node)+','+_type_name(self,right,node)+'))',node)
        from .native_union_sequences import ordering_error
        error=ordering_error(self,operator,left,right,node)
        if error is not None:return error
        raise ClassUnsupported(node)

    def function_name(self, plan):
        from .native_scalar_data_results import function_name as data_function_name
        data_name=data_function_name(self,plan)
        if data_name is not None:return data_name
        from .native_source_state import function_name
        state_name=function_name(self,plan)
        if state_name is not None:return state_name
        return f"class_function_{plan.index}"

    def call_user(self, node, callee, receiver=None, constructor=None,defining_module=None,defining_class=None):
        setup,arguments = [],[]
        if receiver is not None:
            from .native_owned_object_places import call_receiver as owned_call_receiver
            owned_receiver=owned_call_receiver(self,node,callee)
            if owned_receiver is None:
                before,receiver = self.capture(receiver)
            else:
                before,receiver,defining_module=owned_receiver
            setup.append(before)
            arguments.append(receiver)
        try:call_arguments=normalize_call(node)
        except CallBindingError:raise ClassUnsupported(node)from None
        if callee is None:values=[]
        else:
            signature=callee.signature.without_receiver()if constructor is not None else callee.signature
            default_emitter=self.model.emitter(callee)
            def argument_value(expression,parameter):
                before,value=self.capture(self.expression(expression))
                setup.append(before)
                return value
            try:
                from .native_variadic import pack_emission
                call_plan=signature.plan(call_arguments,implicit_count=len(arguments),allow_variadic=True)
                bound=call_plan.capture(argument_value,implicit=arguments,defaults=default_emitter.captured_defaults(callee),pack_positional=lambda members:pack_emission(self,callee,members,node))
            except CallBindingError:raise ClassUnsupported(node)from None
            if constructor is None:
                from .native_frame_specialization import native_target
                callee=native_target(self.model,callee,bound.by_name)
            values=[self.coerce(value,shape(callee.arguments[name]),node)for name,value in zip(bound.parameters,bound.values)]
        name = (f"class_construct_{constructor.index}"if constructor is not None else self.function_name(callee))
        from .native_source_state import call_arguments
        state_arguments=call_arguments(self,node,callee)if callee is not None else None
        if state_arguments is not None:
            name=(f"class_state_construct_{constructor.index}"if constructor is not None else f"class_state_function_{callee.index}")
            values.extend(state_arguments)
        from .native_scalar_data_results import constructor_name,call_name
        name=(constructor_name(self,node,constructor,name)if constructor is not None
              else call_name(self,node,callee,name))
        if constructor is not None:
            from .native_class_identity_demand import token as identity_token
            from .native_class_value_demands import marker_constructor
            prefix=([] if state_arguments is not None and marker_constructor(self.model,constructor)
                    else self.constructor_context_arguments(constructor,defining_class))
            if identity_token(self.model,constructor):
                identity=self.fresh()
                setup.append(f'let {identity}='+self.at('class_value_next_id()',node)+';')
                prefix.append(identity)
            values=prefix+values
        # Constructor futures receive only explicit Python arguments. Their
        # internal __init__ future shares this logical call-stack entry.
        from .native_class_binding_contexts import invocation as class_context_argument
        defining_context=class_context_argument(self.model,callee,None if receiver is None else receiver.code,caller=self.plan,node=node,private=state_arguments is not None)if constructor is None else''
        invocation = name+"(class_scope.clone()"+defining_context+(" ,"+",".join(values)if values else"")+")"
        from .native_class_calls import call as compiled_call
        call = compiled_call(self,invocation,callee,node)
        from .native_scalar_data_results import call_result as data_call_result
        call=data_call_result(self,node,invocation,call)
        context=self.prepare_call_context(callee,receiver,constructor,defining_module,node=node)
        code="{"+"\n".join(setup)+context+call+"}"
        if constructor is not None:
            from .native_tail_constructor_result import register
            register(self,node,constructor,callee,invocation,setup,context)
            return self.encoded(code,InstanceType(self.model.class_key(constructor)),self.kind(node),node)
        from .native_source_returns import emit_result
        return Expression(emit_result(self,node,callee,code,self.kind(node)),self.kind(node))

    def parse_words(self, node, count=None,*,consumer=None):
        from .native_integer_word_maps import parse_immediate
        fused=parse_immediate(self,node,count,consumer=consumer)
        if fused is not None:return fused
        words = self.expression(node.args[1])
        before,words = self.capture(words)
        if domain(words.kind) != "list":
            raise ClassUnsupported(node)
        item = words.kind.element
        if item == 'str':
            parser = "|value:&NativeText|class_parse_text(value)"
        elif item == 'bytes':
            parser = "|value:&Vec<u8>|class_parse_bytes(value)"
        else:
            raise ClassUnsupported(node)
        limit = "None"if count is None else f"Some({count})"
        call = self.at(f"class_parse_words(&{words.code},{limit},{parser})",consumer or node)
        return f"{{{before}{call}}}"

    def sequence_call(self,node,method,*,storage=None):
        if method.name=="sort":
            from .native_class_sorting import emit_method
            return emit_method(self,node)
        from .native_sequence_storage import capture_shared
        from .native_sequence_methods import lower
        emitter=self
        class Adapter:
            bits=emitter.numeric.bits
            temporary=emitter.fresh
            number=emitter.number
            truth=emitter.truth
            at=emitter.at
            from .native_class_storage import shared_element
            shared_element=staticmethod(shared_element)
            def sequence_equal(self,left,right,node):return emitter.comparison(ast.Eq(),left,right,node)
            def sequence_ordering(self,left,right,node):
                from .native_class_storage import ordering
                return ordering(emitter,left,right,node)
            def coerce(self,value,kind):return emitter.coerce(value,kind,node)
            def sequence_type_name(self,value):
                from .native_class_builtins import _type_name
                return _type_name(emitter,value,node)
        adapter=Adapter()
        if storage is None:storage=capture_shared(adapter,self.expression(node.func.value))
        lines=list(storage.setup)
        bound={}
        arguments=normalize_call(node)
        if method.error:
            explicit=tuple((argument,f"argument_{index}")for index,argument in enumerate(arguments.evaluation_order))
        else:
            try:call=method.signature.plan(arguments,implicit_count=1)
            except CallBindingError:raise ClassUnsupported(node)from None
            explicit=zip(call.arguments.evaluation_order,call.argument_parameters)
        for argument,name in explicit:
            before,value=self.capture(self.expression(argument.expression))
            lines.append(before)
            bound[name]=value
        if method.name=="sort"and "key"in bound and bound["key"].kind!="none":
            raise ClassUnsupported(node,"the class-aware sequence path only captures None for list.sort key; retaining and invoking a user key callable once per element is not implemented",types=(("key",bound["key"].kind),),proof="key callable capture and ordered once-per-element evaluation")
        result=lower(adapter,storage,method,bound,node,{},sort_key=None)
        temporary=self.fresh()
        from .native_source_state import append_export
        exported=append_export(self,node,method,bound)
        return self.encoded("{"+"".join(lines)+f"let {temporary}={result.code};"+exported+temporary+"}",result.kind,self.kind(node),node)

    def call(self, node):
        from .native_class_binding_contexts import instance_test
        tested=instance_test(self,node)
        if tested is not None:return tested
        from .native_owned_class_lists import length as owned_field_length
        owned_length=owned_field_length(self,node)
        if owned_length is not None:return owned_length
        from .native_text_join import emit as emit_join
        joined=emit_join(self,node)
        if joined is not None:return joined
        from .native_integer_word_maps import emit_call as emit_integer_words
        words=emit_integer_words(self,node)
        if words is not None:return words
        expanded=self.model.expanded_calls.emit(self,node)
        if expanded is not None:return expanded
        deque=self.model.deques.emit_method(self,node)
        if deque is not None:return deque
        mapped=self.model.mappings.emit_method(self,node)
        if mapped is not None:return mapped
        from .native_aot_callables import emit_call
        dispatched=emit_call(self,node)
        if dispatched is not None:return dispatched
        from .native_frame_references import call_target
        callee=call_target(self.model,self.plan,node)
        if callee is not None:return self.call_user(node,callee)
        method=self.model.sequence_calls.get((self.plan.index,id(node)))
        if method is not None:return self.sequence_call(node,method)
        function = node.func
        wanted = self.kind(node)
        if isinstance(function,ast.Name) and function.id in self.model.classes:
            owner = self.model.classes[function.id]
            return self.call_user(node,owner.methods.get("__init__"),constructor=owner)
        if isinstance(function,ast.Name) and function.id in self.model.functions:
            return self.call_user(node,self.model.functions[function.id])
        if (self.plan.index,id(node))in self.model.condition_calls:
            return self.condition(node.args[0])if node.args else Expression("false","bool",False)
        if isinstance(function,ast.Attribute):
            receiver = self.expression(function.value)
            if domain(receiver.kind) == "object":
                owner = self.model.classes[receiver.kind.name]
                method = owner.methods[self.model.resolved_name(self.plan,function)]
                return self.call_user(node,method,receiver)
        else:
            receiver = None
        if (isinstance(function,ast.Name) and function.id == "list" and len(node.args)==1
                and domain(self.kind(node.args[0])) == "map_int"):
            values = self.parse_words(node.args[0],consumer=node)
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
        from .native_class_stdio import READERS,member as reader_member,emit as emit_reader
        reader=name if name in READERS else reader_member(domain(receiver.kind),function.attr)if receiver is not None else None
        if reader is not None:
            result=emit_reader(self,node,reader,arguments,list(keywords.items()),wanted)
            return Expression("{"+"\n".join(setup)+result.code+"}",wanted)
        code = None
        raw_kind=shape(self.model.constructors[(self.plan.index,id(node))])if(self.plan.index,id(node))in self.model.constructors else wanted
        from .native_class_builtins import SUPPORTED,emit as emit_builtin
        if name in SUPPORTED or name in {"reader_text","reader_bytes","read_text","read_bytes"}:
            result=emit_builtin(self,node,BuiltinIdentity(name),arguments,keywords,wanted,raw_kind)
            return Expression("{"+"\n".join(setup)+"let class_value="+result.code+";class_value}",wanted,result.constant)
        elif receiver is not None:
            from .native_class_splits import emit as emit_split
            split=emit_split(self,node,receiver,arguments,keywords,wanted)
            if split is not None:return Expression("{"+"\n".join(setup)+split.code+"}",wanted)
            from .native_class_text_ops import emit as emit_text_operation
            text_operation=emit_text_operation(self,node,receiver,arguments,keywords,wanted)
            if text_operation is not None:return Expression("{"+"\n".join(setup)+text_operation.code+"}",wanted)
            tag,method=domain(receiver.kind),function.attr
            if tag=="str"and method=="join":
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
        code=self._assign(target,value)
        if isinstance(target,ast.Name):
            from .native_globals_view import store
            code+=store(self,target)
        return code

    def _assign(self,target,value):
        if isinstance(target,ast.Name):
            return self.assign_name(target,value)
        if isinstance(target,(ast.Tuple,ast.List)):
            from .native_class_unpacking import emit
            unpacked=emit(self,target,value)
            if unpacked is not None:return unpacked
            setup,source = self.capture(value)
            if domain(source.kind)=="tuple":
                pieces = [self.assign(node,Expression(f"{source.code}.{i}.clone()",kind))
                          for i,(node,kind)in enumerate(zip(target.elts,source.kind.fields))]
            elif domain(source.kind)=="tuple_sequence":
                setup+=self.at(f'class_tuple_unpack_length({source.code}.len(),{len(target.elts)})',target)+";"
                pieces=[self.assign(node,Expression(f"{source.code}.as_slice()[{i}].clone()",source.kind.element))for i,node in enumerate(target.elts)]
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
        from .native_scalar_data_results import reference as data_reference
        data=data_reference(self,target)
        if data is not None:return data
        from .native_owned_object_places import reference as owned_object_reference
        owned_object=owned_object_reference(self,target)
        if owned_object is not None:return owned_object
        from .native_owned_matrix_places import reference as matrix_reference
        matrix=matrix_reference(self,target)
        if matrix is not None:return matrix
        from .native_record_places import reference as record_reference
        record=record_reference(self,target)
        if record is not None:return record
        from .native_owned_local_lists import reference as owned_reference
        owned=owned_reference(self,target)
        if owned is not None:return owned
        from .native_owned_class_lists import reference as owned_field_reference
        owned_place=owned_field_reference(self,target)
        if owned_place is not None:return owned_place
        from .native_value_classes import reference as value_reference
        borrowed=value_reference(self,target)
        if borrowed is not None:return borrowed
        from .native_list_access_regions import reference as region_reference
        optimized=region_reference(self,target)
        if optimized is not None:return optimized
        if isinstance(target,ast.Name):
            return "",("name",target)
        if isinstance(target,ast.Attribute):
            setup,owner = self.capture(self.expression(target.value))
            from .native_finite_attributes import selected
            if selected(self.model,self.plan,target):return setup,('finite_field',owner,self.kind(target))
            if target.attr=='default_factory':
                from .native_class_defaultdicts import is_default
                if all(is_default(kind)for kind in alternatives(owner.kind)):return setup,('default_factory',owner,self.kind(target))
            if domain(owner.kind)!="object":raise ClassUnsupported(target)
            plan=self.model.classes[owner.kind.name]
            name=self.model.resolved_name(self.plan,target)
            return setup,("field",owner,plan,list(plan.fields).index(name),shape(plan.fields[name].cell))
        if isinstance(target,ast.Subscript):
            setup,owner=self.capture(self.expression(target.value))
            more,index=self.capture(self.expression(target.slice))
            if all(getattr(kind,"_native_class_mapping",False)for kind in alternatives(owner.kind)):
                return setup+more,("mapping",owner,index,self.kind(target))
            if all(domain(kind)=="deque"for kind in alternatives(owner.kind)):
                return setup+more,("deque_index",owner,index,self.kind(target))
            from .native_finite_list_writes import supported
            if supported(owner.kind,index.kind):
                return setup+more,("finite_list_index",owner,index,self.kind(target))
            if domain(owner.kind)!="list":raise ClassUnsupported(target)
            return setup+more,("index",owner,index,owner.kind.element)
        raise ClassUnsupported(target)

    def assign_name(self,target,value):
        lexical=self.model.lexical.emit_store(self,target,value)
        if lexical is not None:return lexical
        from .native_class_globals import assign,local_assign
        shared=assign(self,target,value)
        if shared is not None:return shared
        shared=local_assign(self,target,value)
        if shared is not None:return shared
        kind=self.kind(target)
        name=self.model.resolved_name(self.plan,target)
        clearing="".join(f"{other}=None;"for(other_name,other_kind),other in self.slots.items()
                         if other_name==name and other_kind!=kind)
        clearing+="".join(f"{other}=false;"for(other_name,other_kind),other in self.reference_slots.items()
                          if other_name==name and other_kind!=kind)
        if domain(kind)in self.model.INTRINSICS:return clearing+f"{self.reference_slot(name,kind)}=true;"
        return clearing+f"{self.slot(name,kind)}=Some({self.coerce(value,kind,target)});"

    def load_reference(self, reference, node, kind=None):
        if reference[0]in{'owned_object_field','owned_object_index'}:
            from .native_owned_object_places import load
            return load(self,reference,node,kind)
        if reference[0]=='owned_matrix':
            from .native_owned_matrix_places import load
            return load(self,reference,node,kind)
        if reference[0]=='record_slot':
            from .native_record_places import load
            return load(self,reference,node,kind)
        if reference[0]=='owned_local_list':
            from .native_owned_local_lists import load
            return load(self,reference,node,kind)
        if reference[0]=='owned_class_index':
            from .native_owned_class_lists import load
            return load(self,reference,node,kind)
        if reference[0]=="list_region":
            from .native_list_access_regions import load
            return load(self,reference[1],reference[2],node)
        if reference[0]=='finite_field':
            from .native_finite_attributes import emit
            return emit(self,node,reference[1],kind or reference[2])
        if reference[0]=='finite_list_index':
            from .native_union_sequences import emit_subscript
            return emit_subscript(self,node,reference[1],reference[2],kind or reference[3])
        if reference[0]=="deque_index":
            return self.model.deques.indexes.emit(self,node,reference[1],reference[2],kind or reference[3])
        if reference[0]=='default_factory':
            return Expression(self.model.mappings.defaultdicts.emit_attribute(self,node,reference[1],kind or reference[2]),kind or reference[2])
        if reference[0]=="mapping":
            return self.model.mappings.emit_get(self,node,reference[1],reference[2],kind or reference[3])
        if reference[0]=="name":
            target=reference[1]
            kind=kind or self.kind(target)
            lexical=self.model.lexical.emit_read(self,target,kind)
            if lexical is not None:return lexical
            from .native_class_globals import read
            shared=read(self,target,kind)
            if shared is not None:return shared
            from .native_class_globals import local_read
            shared=local_read(self,target,kind)
            if shared is not None:return shared
            name=self.model.resolved_name(self.plan,target)
            slot=self.slot(name,kind)
            message=f"UnboundLocalError: cannot access local variable '{self.model.display_name(name)}' where it is not associated with a value"
            if self.model.is_module_plan(self.plan):message=f"NameError: name '{self.model.display_name(name)}' is not defined"
            return Expression(self.at(f"{slot}.clone().ok_or_else(||{_string(message)}.to_owned())",node),kind)
        if reference[0]=="field":
            _,owner,plan,index,kind=reference
            return Expression(self.at(f"class_get_{plan.index}_{index}(&{owner.code})",node),kind)
        requested=kind
        _,owner,index,kind=reference
        from .native_list_end_indices import class_get
        endpoint=class_get(self,node,owner,requested or kind)
        if endpoint is not None:return endpoint
        from .native_list_positions import project_element
        raw=self.at(f"class_list_get(&{owner.code},&({self.number(index)}))",node)
        return project_element(self,raw,owner.kind.element,requested or kind,node)

    def store_reference(self, reference, value, node):
        if reference[0]in{'owned_object_field','owned_object_index'}:
            from .native_owned_object_places import store
            return store(self,reference,value,node)
        if reference[0]=='owned_matrix':
            from .native_owned_matrix_places import store
            return store(self,reference,value,node)
        if reference[0]=='record_slot':
            from .native_record_places import store
            return store(self,reference,value,node)
        if reference[0]=='owned_local_list':
            from .native_owned_local_lists import store
            return store(self,reference,value,node)
        if reference[0]=='owned_class_index':
            from .native_owned_class_lists import store
            return store(self,reference,value,node)
        if reference[0]=="list_region":
            from .native_list_access_regions import store
            return store(self,reference[1],reference[2],value,node)
        if reference[0]=='finite_field':
            from .native_finite_attributes import emit
            return emit(self,node,reference[1],'none',value=value).code+';'
        if reference[0]=='finite_list_index':
            from .native_finite_list_writes import emit
            return emit(self,node,reference[1],reference[2],value).code+';'
        if reference[0]=="deque_index":
            return self.model.deques.indexes.emit(self,node,reference[1],reference[2],"none",value).code+";"
        if reference[0]=='default_factory':return self.model.mappings.defaultdicts.emit_attribute_store(self,node,reference[1],value)
        if reference[0]=="mapping":
            return self.model.mappings.emit_store(self,node,reference[1],reference[2],value)
        if reference[0]=="name":
            return self.assign(reference[1],value)
        if reference[0]=="field":
            _,owner,plan,index,kind=reference
            from .native_copy_scalar_fields import store
            return store(self.model,plan,owner.code,index,self.coerce(value,kind,node))
        _,owner,index,kind=reference
        setter=f"class_list_set(&{owner.code},&({self.number(index)}),{self.coerce(value,kind,node)})"
        return self.at(setter,node)+";"

    def statements(self, values):
        reached=getattr(self.model,'reached_statements',None)
        from .native_statement_lifetimes import scope
        return "\n".join(scope(self,value,self.statement(value))for value in values
                         if reached is None or(self.plan.index,id(value))in reached)

    def statement(self, node):
        from .native_scalar_data_locals import statement as snapshot_statement
        snapshot=snapshot_statement(self,node)
        if snapshot is not None:return snapshot
        from .native_scalar_data_results import statement as data_statement
        data=data_statement(self,node)
        if data is not None:return data
        from .native_source_state import explicit_return
        state_return=explicit_return(self,node)
        if state_return is not None:return state_return
        from .native_owned_object_places import initialize as initialize_owned_object_field
        owned_object=initialize_owned_object_field(self,node)
        if owned_object is not None:return owned_object
        from .native_owned_matrix_places import statement as matrix_statement
        matrix=matrix_statement(self,node)
        if matrix is not None:return matrix
        from .native_record_places import statement as record_statement
        record=record_statement(self,node)
        if record is not None:return record
        from .native_owned_local_lists import statement as owned_statement
        owned=owned_statement(self,node)
        if owned is not None:return owned
        from .native_owned_class_lists import initialize as initialize_owned_field
        initialized=initialize_owned_field(self,node)
        if initialized is not None:return initialized
        if isinstance(node,ast.Raise):return self.model.exceptions.emit_raise(self,node)
        from .native_context_managers import control_statement
        control=control_statement(self,node)
        if control is not None:return control
        if isinstance(node,ast.With):return self.model.context_managers.emit(self,node)
        if isinstance(node,(ast.Import,ast.ImportFrom)):
            imported=self.emit_import(node)
            if imported is not None:return imported
        if isinstance(node,(ast.ClassDef,ast.FunctionDef)):
            lexical=self.model.lexical.emit_define(self,node)
            if lexical is not None:return lexical
            from .native_class_globals import define
            return define(self,node)
        if isinstance(node,ast.Import):
            from .native_globals_view import imported
            return imported(self,node)
        from .native_annotations import future_directive
        if isinstance(node,(ast.Pass,ast.Global,ast.Nonlocal))or future_directive(node):
            return ""
        if isinstance(node,ast.Expr):
            if isinstance(node.value,ast.Constant)and type(node.value.value)is str:
                return ""
            return self.expression(node.value).code+";"
        if isinstance(node,ast.Assert):
            from .native_assertions import lower
            return lower(self,node)
        if isinstance(node,ast.AnnAssign):
            if node.value is not None:
                setup,value=self.capture(self.expression(node.value))
                return setup+self.assign(node.target,value)
            from .native_annotations import target_inputs
            return ''.join(self.expression(expression).code+';'for expression in target_inputs(node.target))
        if isinstance(node,ast.Assign):
            from .native_frame_references import alias_assignment
            if alias_assignment(self.model,self.plan,node):return ''
            from .native_integer_word_maps import emit_unpack_assignment
            unpacked_words=emit_unpack_assignment(self,node)
            if unpacked_words is not None:return unpacked_words
            if domain(self.kind(node.value))=="map_int":
                if len(node.targets)!=1 or not isinstance(node.targets[0],(ast.Tuple,ast.List)):
                    raise ClassUnsupported(node)
                target=node.targets[0];temporary=self.fresh()
                setup=f"let {temporary}={self.parse_words(node.value,len(target.elts),consumer=node)};"
                return setup+"".join(self.assign(value,Expression(f"{temporary}[{i}].clone()",'int'))
                                     for i,value in enumerate(target.elts))
            setup,value=self.capture(self.expression(node.value))
            return setup+"".join(self.assign(target,value if index+1==len(node.targets)
                else Expression(value.code+".clone()",value.kind,value.constant))
                for index,target in enumerate(node.targets))
        if isinstance(node,ast.Delete):
            from .native_class_deletion import lower
            from .native_class_globals import delete
            pieces=[]
            for target in node.targets:
                code=lower(self,target)
                if code is None:
                    code=self.model.lexical.emit_delete(self,target)if self.model.lexical.field_for(target)is not None else delete(self,target)
                pieces.append(code)
            return ''.join(pieces)
        if isinstance(node,ast.AugAssign):
            setup,reference=self.reference(node.target)
            old_kind=shape(self.model.augmented[(self.plan.index,id(node))])
            from .native_integer_list_places import emit as integer_places
            fused=integer_places(self,node,setup,reference,old_kind)
            if fused is not None:return fused
            from .native_list_access_regions import augmented
            fused=augmented(self,node,setup,reference,old_kind)
            if fused is not None:return fused
            from .native_class_augassign import emit
            fused=emit(self,node,setup,reference,old_kind)
            if fused is not None:return fused
            before,old=self.capture(self.load_reference(reference,node.target,old_kind))
            more,right=self.capture(self.expression(node.value))
            from .native_record_places import target_kind
            wanted=target_kind(self,reference,node.target)
            if wanted is None:wanted=self.kind(node.target)
            if domain(old.kind)=="list"and isinstance(node.op,ast.Add)and domain(right.kind)=="list":
                operation=f"class_list_extend(&{old.code},&{right.code});"
                result=Expression(old.code,old.kind)
            elif domain(old.kind)=="list"and isinstance(node.op,ast.Mult)and domain(right.kind)in {"int","bool","int_bool"}:
                operation=self.at(f"class_list_repeat_in_place(&{old.code},&({self.number(right)}))",node)+";"
                result=Expression(old.code,old.kind)
            else:
                result=self.binary(node.op,old,right,node,wanted)
                operation=""
            result_setup,result=self.capture(result)
            return setup+before+more+operation+result_setup+self.store_reference(reference,result,node.target)
        if isinstance(node,ast.Return):
            if node.value is None:value=Expression("()",'none')
            else:
                from .native_tail_constructor_result import capture
                with capture(self,node.value)as tail:value=self.expression(node.value)
                if tail is not None and tail.code is not None:return 'return '+tail.code+';'
            return f"return Ok({self.coerce(value,shape(self.plan.result),node)});"
        if isinstance(node,ast.If):
            setup,test=self.capture(self.condition(node.test))
            from .native_guard_flow import emit
            selected=emit(self,node,setup,test)
            if selected is not None:return selected
            return setup+f"if {self.truth(test)}{{\n{self.statements(node.body)}\n}}else{{\n{self.statements(node.orelse)}\n}}"
        if isinstance(node,ast.While):
            from .native_loop_else import condition as loop_condition,enter,leave
            if loop_condition(self.model,node)is False:
                setup,test=self.capture(self.condition(node.test))
                return '{'+setup+'let _='+test.code+';'+self.statements(node.orelse)+'}'
            label=self.fresh()
            self.loops.append(label)
            flags=enter(self,node,label)
            from .native_class_loop_fields import scope
            from .native_list_access_regions import scope as access_scope
            with scope(self,node)as cache,access_scope(self,node)as access:
                setup,test=self.capture(self.condition(node.test))
                body=self.statements(node.body)
            cache+=access
            self.loops.pop()
            from .native_list_access_regions import tail_scope
            with tail_scope(self,node):tail=leave(self,node,label)
            return "{"+flags+cache+f"'{label}:loop{{{setup}if !({self.truth(test)}){{break;}}{body}}}"+tail+"}"
        if isinstance(node,ast.For):
            return self.for_statement(node)
        if isinstance(node,ast.Break):
            from .native_loop_else import transfer
            return transfer(self,False)+';'
        if isinstance(node,ast.Continue):
            from .native_loop_else import transfer
            return transfer(self,True)+';'
        raise ClassUnsupported(node)

    def for_statement(self, node):
        iterable=node.iter
        enumerated=(isinstance(iterable,ast.Call)and isinstance(iterable.func,ast.Name)
                    and iterable.func.id=="enumerate"and domain(self.kind(iterable))=="enumerate")
        source_node=iterable.args[0]if enumerated else iterable
        from .native_owned_local_lists import iteration as owned_iteration,enumerate_source
        owned=owned_iteration(self,source_node)
        if owned is None and not enumerated:
            immediate=enumerate_source(self,iterable)
            if immediate is not None:
                owned=owned_iteration(self,immediate)
                if owned is not None:enumerated=True;source_node=immediate
        setup,source=owned if owned is not None else self.capture(self.expression(source_node))
        from .native_class_iterators import tuple_cursor_required
        if self.model.iterators.needs_source_cursor(source.kind) or tuple_cursor_required(source.kind):
            before,source=self.capture(self.model.iterators.construct(self,node,source));setup+=before
        counter=None
        if enumerated:
            start=self.expression(iterable.args[1])if len(iterable.args)==2 else Expression(self.literal(0),'int',0)
            counter=self.fresh()
            setup+=f"let mut {counter}={self.number(start)};"
        label=self.fresh();self.loops.append(label)
        from .native_loop_else import enter,leave
        setup+=enter(self,node,label)
        from .native_class_loop_fields import scope
        from .native_list_access_regions import scope as access_scope
        with scope(self,node)as cache,access_scope(self,node)as access:
            body=self.statements(node.body)
        cache+=access
        setup+=cache
        self.loops.pop()
        current=self.fresh()
        if domain(source.kind)=="iterator":
            pulled=self.model.iterators.pull(self,node,source)
            prefix=f"'{label}:loop{{let Some({current})=({pulled.code}) else{{break;}};"
            item=Expression(current,pulled.kind)
        elif domain(source.kind)=="list":
            index=self.fresh()
            setup+=f"let mut {index}=0_usize;"
            advance=self.at(f"{index}.checked_add(1).ok_or_else(||\"OverflowError: list iterator index overflow\".to_owned())",node)
            owner=source.code if owned is not None else source.code+'.borrow()'
            prefix=f"'{label}:loop{{let {current}={{{owner}.get({index}).cloned()}};let Some({current})={current} else{{break;}};{index}={advance};"
            item=Expression(current,source.kind.element)
        elif domain(source.kind)=="tuple_sequence":
            prefix=f"'{label}:for {current} in {source.code}.iter().cloned(){{"
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
        from .native_list_access_regions import tail_scope
        with tail_scope(self,node):tail=leave(self,node,label)
        return "{"+setup+prefix+before+binding+body+"}"+tail+"}"

    def declaration(self):
        from .native_value_classes import borrowed_self
        from .native_owned_object_places import receiver as owned_receiver
        from .native_local_storage import rust_type as local_storage_type
        from .native_primitive_parameter_places import slot_required
        from .native_operand_demands import private_projection
        from .native_scalar_constructor_data import receiver_type
        from .native_scalar_data_parameters import parameter as data_parameter
        projection=private_projection(self)
        erased=projection.erased_names if projection is not None else frozenset()
        data=[f"let mut {slot}:Option<"+('&'+receiver_type(self.model,self.plan,name)
              if receiver_type(self.model,self.plan,name)is not None else
              f"&{self.rust_type(kind)}"if borrowed_self(self.model,self.plan,name,kind)else local_storage_type(self,name,kind))+">=None;"for(name,kind),slot in self.slots.items()if name not in erased and not owned_receiver(self.model,self.plan,name)and slot_required(self,name,kind)and data_parameter(self.model,self.plan,name)is None]
        references=[f"let mut {slot}=false;"for slot in self.reference_slots.values()]
        return "\n".join(data+references)

    def generate(self):
        from .native_source_generators import generate as generate_source_generator
        generator=generate_source_generator(self)
        if generator is not None:return generator
        from .native_typed_continuations import generate as generate_continuation
        continuation=None if getattr(self,'native_direct_body',False)else generate_continuation(self)
        if continuation is not None:return continuation
        from .native_operand_demands import private_projection
        projection=private_projection(self)
        erased=projection.erased_names if projection is not None else frozenset()
        if isinstance(self.plan.node,ast.Lambda):
            value=self.expression(self.plan.node.body)
            body="return Ok("+self.coerce(value,shape(self.plan.result),self.plan.node.body)+");"
        else:body=self.statements(self.plan.node.body)
        parameters=[];initial=[]
        from .native_primitive_parameter_places import slot_required
        for i,name in enumerate(self.plan.runtime_parameters):
            if name in erased:continue
            kind=shape(self.plan.arguments[name]);argument=f"class_argument_{i}"
            from .native_value_classes import borrowed_self
            reference=borrowed_self(self.model,self.plan,name,kind)
            from .native_owned_object_places import receiver as owned_receiver
            mutable=owned_receiver(self.model,self.plan,name)
            from .native_scalar_constructor_data import receiver_type
            receiver=receiver_type(self.model,self.plan,name)
            from .native_scalar_data_parameters import parameter_type
            view=parameter_type(self.model,self.plan,name)
            parameters.append(f"{argument}:"+(view if view is not None else'&'+receiver if receiver is not None else
                ('&mut 'if mutable else'&'if reference else'')+self.rust_type(kind)))
            if view is not None:continue
            if mutable or not slot_required(self,name,kind):continue
            captured=self.model.lexical.environments.get(self.model.lexical.scope(self.plan))
            if captured is not None and name in captured.fields:continue
            stored=self.model.namespace.local_kind(self.plan,name)or kind
            initial.append(f"{self.slot(name,stored)}=Some({self.coerce(Expression(argument,kind),stored,self.plan.node)});")
        from .native_scalar_data_results import result_type as data_result_type
        result=data_result_type(self)or self.rust_type(shape(self.plan.result))
        if "none"in alternatives(shape(self.plan.result)):
            tail="Ok("+self.coerce(Expression("()","none"),shape(self.plan.result),self.plan.node)+")"
        else:
            tail=f"Err(native_error(\"RuntimeError: invalid compiled return\".into(),{getattr(self.plan.node,'lineno',1)},{self.location_code()}))"
        lexical_initial=self.model.lexical.initialize(self)
        from .native_class_binding_contexts import parameter as class_context_parameter
        signature="class_scope:ClassScope"+self.model.lexical.signature(self.plan)+class_context_parameter(self.model,self.plan,private=getattr(self,'source_state_private',False))+(" ,"+",".join(parameters)if parameters else"")
        from .native_source_state import extra_parameters,producer_result
        signature+=extra_parameters(self)
        result,tail,state_initial=producer_result(self,result,tail)
        lexical_initial=state_initial+lexical_initial
        from .native_class_calls import entry_result
        if entry_result(self.model,self.plan):
            from .native_call_context_effects import inline_entry
            from .native_source_state import inline_entry as private_inline_entry
            private_inline=(getattr(self,'source_state_private',False)
                            and private_inline_entry(self.model,self.plan))
            inline="#[inline(always)]\n"if private_inline or inline_entry(self.model,self.plan)else""
            return (inline+f"fn {self.function_name(self.plan)}({signature})->ClassResult<{result}>{{\n"
                    "use std::fmt::Write as _;\n"+(lexical_initial+"\n"if lexical_initial else"")+self.declaration()+"\n"+"\n".join(initial)+"\n"+body+"\n"+tail+"\n}")
        return (f"fn {self.function_name(self.plan)}({signature})->ClassFuture<{result}>{{Box::pin(async move{{\n"
                "use std::fmt::Write as _;\n"+(lexical_initial+"\n"if lexical_initial else"")+self.declaration()+"\n"+"\n".join(initial)+"\n"+body+"\n"+tail+"\n})}")


def _named_helpers(source,wanted):
    """Select complete shared Rust primitives without unrelated owner impls."""
    from .rust_pruning import select_named_rust_items
    return select_named_rust_items(source,wanted)


def _text_helpers(runtime):
    """Use the shared Unicode-aware repr primitives without object-runtime code."""
    return _named_helpers(runtime.joinpath("text.rs").read_text(encoding="utf-8"),
                          {"TEXT_PRINTABLE","text_property","text_repr_str","text_repr_bytes"})


def _structural_helpers(integer):
    if integer=="bigint":
        index="let index=index.to_i128()?;"
        count="if count.is_negative(){return Ok(0);}let count=count.to_i128().ok_or_else(||\"OverflowError: cannot fit 'int' into an index-sized integer\".to_string())?;"
        recursion="let value=value.to_i128().ok_or_else(||\"OverflowError: Python int too large to convert to C int\".to_string())?;"
        from_usize="Int::from_i128(value as i128)"
    else:
        index="let index=*index;"
        count="let count=*count as i128;if count<0{return Ok(0);}"
        recursion="let value=*value as i128;"
        from_usize="value as NativeInt"
    return """
fn class_normalize_index(index:&NativeInt,length:usize)->Option<usize> {
    """+index+"""
    if index<0{usize::try_from(index.unsigned_abs()).ok().and_then(|distance|length.checked_sub(distance))}
    else{usize::try_from(index).ok()}
}
fn class_index(index:&NativeInt,length:usize)->Result<usize,String> {
    class_normalize_index(index,length).filter(|&offset|offset<length)
        .ok_or_else(||"IndexError: list index out of range".into())
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
    from .native_class_calls import synchronous
    result=[]
    for owner in model.classes.values():
        if not owner.used:continue
        from .native_copy_scalar_fields import selected,load
        copied=selected(model,owner)
        from .native_owned_object_places import selected as object_owned
        owned_object=object_owned(model,owner)
        from .native_value_classes import selected as value_selected
        unboxed=value_selected(model,owner)
        from .native_class_identity_demand import token as identity_token,elided as identity_elided
        has_identity=identity_token(model,owner)
        from .native_packed_value_fields import selected as packed_selected,initial as packed_initial,raw as packed_raw
        packed=packed_selected(model,owner)
        from .native_scalar_constructor_data import selected as data_constructor
        stack_constructor=data_constructor(model,owner)
        fields=list(owner.fields.values())
        from .native_owned_class_lists import selected as owned_field_selected,runtime as owned_field_runtime,physical_type as owned_field_type
        from .native_constant_field_projection import selected as constant_selected,read as constant_read
        from .native_initialized_owned_fields import selected as initialized_field,initial as initialized_default
        members=",".join(f"field_{i}:"+((owned_field_type(model,owner,i,emitter)if owned_field_selected(model,owner,i)else emitter.rust_type(shape(value.cell)))if initialized_field(model,owner,i)else f"Option<{owned_field_type(model,owner,i,emitter)}>"if owned_field_selected(model,owner,i)else f"std::cell::Cell<{emitter.rust_type(shape(value.cell)if packed else MaybeType(shape(value.cell)))}>"if copied else emitter.rust_type(MaybeType(shape(value.cell))))for i,value in enumerate(fields)if not constant_selected(model,owner,i))
        extra_member,extra_parameter,extra_initialize=model.class_runtime_context(owner)
        from .native_class_binding_contexts import borrowed_constructor
        if borrowed_constructor(model,owner)and extra_parameter=='class_definition:ClassClassRef':
            extra_parameter='class_definition:&ClassClassRef'
        from .native_static_class_metadata import layout as metadata_layout
        extra_member,extra_initialize,metadata_runtime=metadata_layout(model,owner,extra_member,extra_initialize)
        if metadata_runtime:result.append(metadata_runtime)
        if extra_member:members=extra_member+(","+members if members else"")
        if unboxed:
            if has_identity:members='class_value_identity:usize'+(','+members if members else'')
            result.append(f"#[derive(Clone)]\nstruct ClassData_{owner.index}{{{members}}}\ntype ClassHandle_{owner.index}=ClassData_{owner.index};"
                          f"impl ClassData_{owner.index}{{fn borrow(&self)->&Self{{self}}fn borrow_mut(&self)->&Self{{self}}}}"
                          f"impl AsRef<ClassData_{owner.index}> for ClassData_{owner.index}{{fn as_ref(&self)->&Self{{self}}}}")
        elif owned_object:
            result.append(f"struct ClassData_{owner.index}{{{members}}}\ntype ClassHandle_{owner.index}=ClassData_{owner.index};"
                          f"impl ClassData_{owner.index}{{fn borrow(&self)->&Self{{self}}fn borrow_mut(&mut self)->&mut Self{{self}}}}")
        elif copied:
            result.append(("#[derive(Clone)]\n"if stack_constructor else"")+f"struct ClassData_{owner.index}{{{members}}}\ntype ClassHandle_{owner.index}=Rc<ClassData_{owner.index}>;"
                          f"impl ClassData_{owner.index}{{fn borrow(&self)->&Self{{self}}fn borrow_mut(&self)->&Self{{self}}}}")
            if stack_constructor:
                result.append(f"impl AsRef<ClassData_{owner.index}> for ClassData_{owner.index}{{fn as_ref(&self)->&Self{{self}}}}")
        else:
            result.append(f"struct ClassData_{owner.index}{{{members}}}\ntype ClassHandle_{owner.index}=Rc<RefCell<ClassData_{owner.index}>>;")
        from .native_class_gc import layout as gc_layout,registration as gc_registration
        gc_body=gc_layout(model,owner)
        if gc_body:result.append(gc_body)
        for i,value in enumerate(fields):
            if owned_field_selected(model,owner,i):continue
            message=_string(f"AttributeError: '{owner.node.name}' object has no attribute '{value.name}'")
            argument=f'impl AsRef<ClassHandle_{owner.index}>'if unboxed else f'impl AsRef<ClassData_{owner.index}>'if stack_constructor else f'&ClassHandle_{owner.index}'
            receiver='value.as_ref()'if unboxed or stack_constructor else'value'
            projected=constant_read(model,owner,receiver,i)
            if projected is not None:getter='Ok('+projected+')'
            elif initialized_field(model,owner,i):getter=f'Ok(({receiver}).borrow().field_{i}.clone())'
            else:
                getter='Ok('+packed_raw(receiver,i)+')'if packed else load(model,owner,receiver,i)+f'.ok_or_else(||{message}.to_owned())'
                from .native_scalar_heap_constants import getter as constant_getter
                getter=constant_getter(emitter,owner,i,getter)
            result.append(f"fn class_get_{owner.index}_{i}(value:{argument})->Result<{emitter.rust_type(shape(value.cell))},String>{{{getter}}}")
        field_runtime=owned_field_runtime(model,owner,emitter)
        if field_runtime:result.append(field_runtime)
        if not identity_elided(model,owner)and not owned_object:
            identity='self.class_value_identity'if unboxed else'Rc::as_ptr(self)as usize'
            result.append(f"impl ClassDisplay for ClassHandle_{owner.index}{{fn class_str(&self)->String{{format!(\"<{owner.module_name}.{owner.node.name} object at 0x{{:x}}>\",{identity})}}}}")
        constructor=owner.methods.get("__init__")
        params=[];args=[]
        if constructor:
            for i,name in enumerate(constructor.signature.parameters[1:]):
                from .native_scalar_data_parameters import parameter_type
                view=parameter_type(model,constructor,name)
                params.append(f"argument_{i}:{view or emitter.rust_type(shape(constructor.arguments[name]))}")
                args.append(f"argument_{i}")
        if has_identity:params.insert(0,'class_value_identity:usize')
        if extra_parameter:params.insert(0,extra_parameter)
        signature="class_scope:ClassScope"+(","+",".join(params)if params else"")
        initialize=",".join(f"field_{i}:"+(initialized_default(model,owner,i)if initialized_field(model,owner,i)else'std::cell::Cell::new('+packed_initial(shape(fields[i].cell))+')'if packed else'std::cell::Cell::new(None)'if copied else'None')for i in range(len(fields))if not constant_selected(model,owner,i))
        if extra_initialize:initialize=extra_initialize+(","+initialize if initialize else"")
        if has_identity:initialize='class_value_identity'+(','+initialize if initialize else'')
        body=(f"let mut object=ClassData_{owner.index}{{{initialize}}};"if owned_object else
              f"let object=ClassData_{owner.index}{{{initialize}}};"if unboxed or stack_constructor else
              f"let object=Rc::new(ClassData_{owner.index}{{{initialize}}});"if copied else
              f"let object=Rc::new(RefCell::new(ClassData_{owner.index}{{{initialize}}}));")
        body+=gc_registration(model,owner)
        allocation_body=body
        if constructor:
            suffix="?;"if synchronous(model,constructor)else".await?;"
            receiver='&mut object'if owned_object else'&object'if unboxed or stack_constructor else'object.clone()'
            body+=f"class_function_{constructor.index}(class_scope.clone(),{receiver}"+(","+",".join(args)if args else"")+ ")"+suffix
        if synchronous(model,constructor):
            wrapped='Rc::new(object)'if stack_constructor else'object'
            result.append(f"fn class_construct_{owner.index}({signature})->ClassResult<ClassHandle_{owner.index}>{{{body}Ok({wrapped})}}")
            if stack_constructor:
                result.append(f"#[inline(always)]\nfn class_build_{owner.index}({signature})->ClassResult<ClassData_{owner.index}>{{{body}Ok(object)}}")
        else:
            result.append(f"fn class_construct_{owner.index}({signature})->ClassFuture<ClassHandle_{owner.index}>{{Box::pin(async move{{{body}Ok(object)}})}}")
        if constructor:
            from .native_source_state import constructor as state_constructor
            marker_params=[parameter for parameter in params if parameter!=extra_parameter]
            marker_signature="class_scope:ClassScope"+(","+",".join(marker_params)if marker_params else"")
            state_body=state_constructor(model,emitter,owner,signature,allocation_body,receiver,args,marker_signature=marker_signature)
            if state_body:result.append(state_body)
    from .native_class_identity_demand import runtime_needed as identity_runtime_needed
    if identity_runtime_needed(model):
        from .native_value_classes import RUNTIME
        result.insert(0,RUNTIME)
    return "\n".join(result)


def try_generate_classes(source,filename,integer,*,trusted_imports=frozenset(),prune_output=True,diagnostic_out=None,unit=None,
                         string_mode="ascii",frame_selection=None,model_factory=None):
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
        factory=Model if model_factory is None else model_factory
        model=factory(tree,filename,integer,trusted_imports,unit=unit,string_mode=string_mode)
        model.frame_selection=frame_selection
        model.run()
        from .native_integer_word_maps import prepare as prepare_integer_words
        prepare_integer_words(model)
        from .native_class_calls import classify,synchronous,runtime as call_runtime
        classify(model)
        from .native_value_classes import prepare as prepare_value_classes
        prepare_value_classes(model)
        from .native_class_identity_demand import prepare as prepare_identity_demand
        prepare_identity_demand(model)
        from .native_call_context_effects import prepare as prepare_context_effects
        prepare_context_effects(model)
        from .native_callable_field_demand import prepare as prepare_callable_field_demand
        prepare_callable_field_demand(model)
        from .native_scalar_heap_constants import prepare as prepare_scalar_constants
        prepare_scalar_constants(model)
        model.initialized_lexical_scalars.refine_contexts()
        if model.callable_field_demand is not None:
            model.callable_field_demand.refresh_contexts()
        from .native_class_binding_contexts import prepare as prepare_class_bindings
        prepare_class_bindings(model)
        from .native_owned_class_lists import prepare as prepare_owned_fields
        prepare_owned_fields(model)
        from .native_owned_object_places import prepare as prepare_owned_objects
        prepare_owned_objects(model)
        from .native_initialized_owned_fields import prepare as prepare_initialized_fields
        prepare_initialized_fields(model)
        from .native_value_parameter_borrows import prepare as prepare_parameter_borrows
        prepare_parameter_borrows(model)
        from .native_class_reference_borrows import prepare as prepare_class_reference_borrows
        prepare_class_reference_borrows(model)
        from .native_packed_value_fields import prepare as prepare_packed_fields
        prepare_packed_fields(model)
        from .native_scalar_constructor_data import prepare as prepare_constructor_data
        prepare_constructor_data(model)
        from .native_constant_field_projection import prepare as prepare_constant_projection
        prepare_constant_projection(model)
        from .native_typed_continuations import prepare as prepare_continuations
        prepare_continuations(model)
        from .native_source_state import prepare as prepare_source_state
        prepare_source_state(model)
        from .native_private_module_demands import prepare as prepare_private_module_demands
        prepare_private_module_demands(model)
        from .native_published_metadata import prepare as prepare_published_metadata
        prepare_published_metadata(model)
        from .native_class_value_demands import prepare as prepare_class_value_demands
        prepare_class_value_demands(model)
        from .native_scalar_data_parameters import prepare as prepare_scalar_data_parameters
        prepare_scalar_data_parameters(model)
        from .native_scalar_data_results import prepare as prepare_scalar_data_results
        prepare_scalar_data_results(model)
        from .native_scalar_data_locals import prepare as prepare_scalar_data_locals
        prepare_scalar_data_locals(model)
        emitters=[model.emitter(plan)for plan in model.plans if plan.reachable]
        bodies=[emitter.generate()for emitter in emitters]
        from .native_source_state import bodies as source_state_bodies
        bodies.extend(source_state_bodies(model))
        from .native_scalar_data_results import bodies as scalar_data_bodies
        bodies.extend(scalar_data_bodies(model))
        from .native_text_join import runtime as integer_join_runtime
        joined=integer_join_runtime(model)
        if joined:bodies.append(joined)
        from .native_typed_continuations import runtime as continuation_runtime
        continuation_support=continuation_runtime(model)
        if continuation_support:bodies.append(continuation_support)
        layouts=_class_layouts(model,emitters[0])
        layouts=model.iterators.runtime(emitters[0])+"\n"+layouts
        layouts=model.mappings.runtime(emitters[0])+"\n"+layouts
        layouts=model.deques.runtime()+"\n"+layouts
        unions={}
        kind_closure=set()
        empty_required=False
        def add_kind(kind):
            nonlocal empty_required
            if kind is None or kind in kind_closure:return
            kind_closure.add(kind)
            if isinstance(kind,EmptyType):empty_required=True
            if isinstance(kind,UnionType):
                unions[kind]=None
                for alternative in kind.alternatives:add_kind(alternative)
            elif isinstance(kind,(NullableType,MaybeType)):add_kind(kind.value)
            elif isinstance(kind,TupleType):
                for field in kind.fields:add_kind(field)
            elif isinstance(kind,(ListType,TupleSequenceType)):add_kind(kind.element)
            for child in getattr(kind,'_native_owned_kinds',()):add_kind(child)
        for value in model.records.values():add_kind(shape(value))
        for record in model.iterators.records:
            if record.emitted:
                add_kind(record.kind)
                add_kind(shape(record.element))
        for record in model.deques.records:add_kind(record.kind)
        for record in model.mappings.records:
            add_kind(shape(record.key));add_kind(shape(record.value))
        for kind in model.expanded_calls.kinds():add_kind(kind)
        from .native_class_extrema import kinds as extrema_kinds
        for kind in extrema_kinds(model):add_kind(kind)
        from .native_owned_kinds import kinds as operation_kinds
        for kind in operation_kinds(model):add_kind(kind)
        for _,kind in model.namespace.fields():add_kind(kind)
        for _,kind in model.namespace.default_fields():add_kind(kind)
        for value in model.namespace.local_schemas.values():add_kind(shape(value))
        for plan in model.plans:
            if plan.reachable:
                add_kind(shape(plan.result))
                for value in plan.arguments.values():add_kind(shape(value))
        for owner in model.classes.values():
            if owner.used:
                for value in owner.fields.values():add_kind(shape(value.cell))
        lexical_layouts=model.lexical.runtime(emitters[0])
        lambda_layouts=model.lambda_cells.runtime(emitters[0])
        if lambda_layouts:lexical_layouts+=("\n"if lexical_layouts else"")+lambda_layouts
        layouts=(lexical_layouts+"\n"if lexical_layouts else"")+model.callable_cells.runtime()+"\n"+"\n".join(union_declaration(kind,emitters[0].rust_type)for kind in unions)+"\n"+layouts
    except (SyntaxError,_Unsupported,RecursionError)as error:
        if diagnostic_out is not None:
            node=getattr(error,"node",None)
            origin=unit.original_unit(node)if node is not None and hasattr(unit,"original_unit")else unit
            diagnostic_out.append(_direct_diagnostic(origin.source,origin.filename,error,unit=origin))
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
                       "fn native_parse_integer(value:&str)->Result<Int,String>{Int::parse(value,10)}",
                       "fn native_parse_bytes_integer(value:&[u8])->Result<Int,String>{Int::parse_ascii(value,10)}"])
        if getattr(model,"formatting_required",False)or any(has_float_payload(shape(value))for value in model.records.values()):
            from .native_scalar import SCALAR_HELPERS
            pieces.extend([_named_helpers(SCALAR_HELPERS,{"native_float_text","native_float_div","native_float_divmod"}|getattr(model,"native_float_parsers",set())),
                           "impl ClassDisplay for f64 {fn class_str(&self)->String{native_float_text(*self)}}"])
    else:
        from .native_scalar import SCALAR_HELPERS
        from .native_integer_parsing import render_helpers as parsing_helpers
        pieces.extend([_HELPERS,_named_helpers(_INPUT_HELPERS,{"native_space"}),parsing_helpers(string_mode),_SCALAR_UNION_HELPERS,SCALAR_HELPERS,
                       "fn native_parse_bytes_integer(value:&[u8])->Result<NativeInt,String>{native_fixed_parse_ascii(value).ok_or_else(native_fixed_int_invalid)}",
                       "impl ClassDisplay for f64 {fn class_str(&self)->String{native_float_text(*self)}}"])
    if model.sequence_calls:
        from .native_typed_lists import HELPERS as sequence_helpers
        pieces.append(sequence_helpers)
    from .native_class_globals import runtime as global_runtime
    class_runtime=global_runtime(call_runtime(runtime.joinpath("native_classes.rs").read_text(encoding="utf-8"),model),model,emitters[0])
    if string_mode=="unicode" and not model.string_repr_required:
        class_runtime=class_runtime.replace("    fn class_repr(&self)->String{text_repr_str(self)}\n", "")
    from .native_builtin_singletons import runtime as singleton_runtime
    singleton_layout=singleton_runtime(model)
    if singleton_layout:pieces.append(singleton_layout)
    from .native_variadic import runtime as variadic_runtime
    pieces.append(variadic_runtime(model))
    from .native_class_materialization import empty_runtime
    pieces.append(empty_runtime(model,empty_required))
    from .native_formatting import runtime as format_runtime
    pieces.append(format_runtime(model))
    from .native_integer_base import runtime as integer_base_runtime
    pieces.append(integer_base_runtime(model))
    from .native_class_splits import runtime as split_runtime
    pieces.append(split_runtime(model))
    from .native_class_text_ops import runtime as text_operation_runtime
    pieces.append(text_operation_runtime(model))
    exception_payloads=model.exceptions.payloads(emitters[0])
    if exception_payloads:pieces.append(exception_payloads)
    from .native_cmp_keys import runtime as comparison_key_runtime
    pieces.append(comparison_key_runtime(model,emitters[0]))
    from .native_starred_calls import runtime as expanded_runtime
    pieces.append(expanded_runtime(model))
    from .native_frame_slices import runtime as slice_runtime
    pieces.append(slice_runtime(model))
    pieces.extend([_OUTPUT_HELPERS,runtime.joinpath("streaming_io.rs").read_text(encoding="utf-8"),
                   _text_helpers(runtime),_structural_helpers(integer),class_runtime,layouts,*bodies])
    from .native_integer_list_places import runtime as integer_place_runtime
    pieces.append(integer_place_runtime(model))
    if getattr(model,'owned_list_repetition',False):
        from .native_owned_local_lists import RUNTIME as owned_list_runtime
        pieces.append(owned_list_runtime)
    from .native_class_calls import entry_result
    entry=("scope.control.borrow_mut().depth=1;let result=class_function_0(scope.clone());"if entry_result(model,model.module)
           else "let result=class_execute(scope.clone(),class_function_0(scope.clone()));")
    pieces.append("fn main(){use std::io::Write as _;let scope=ClassScope::new();"+entry+"\n"
                  "std::io::stdout().write_all(scope.io.borrow().output.as_bytes()).unwrap();\n"
                  'if let Err(error)=result {eprintln!("Traceback (most recent call last):");\n'
                  'for &(line,function)in error.frames.iter().rev(){\n'
                  f'eprintln!("  File {{:?}}, line {{}}, in {{}}",{_string(filename)},line,function);}}\n'
                  f'eprintln!("  File {{:?}}, line {{}}, in {{}}\\n{{}}",{_string(filename)},error.line,error.function,error.message);std::process::exit(1);}}}}')
    result=model.finish_runtime(model.generators.runtime("\n".join(pieces)))
    from .native_context_managers import runtime as context_runtime
    result=context_runtime(result,model)
    from .native_exception_runtime import runtime as exception_runtime
    result=exception_runtime(result,model)
    from .native_class_gc import runtime as gc_runtime
    result=gc_runtime(result,model)
    from .native_text_policy import apply_text_policy
    result=apply_text_policy(result,string_mode)
    from .native_cached_text import apply_cached_text
    result=apply_cached_text(result,string_mode,class_repr=model.string_repr_required)
    from .native_exit import runtime as exit_runtime
    result=exit_runtime(result,model)
    from .native_scope_borrows import apply as borrow_scope_abi
    result=borrow_scope_abi(result)
    from .native_value_parameter_borrows import apply as apply_parameter_borrows
    result=apply_parameter_borrows(result,model)
    from .native_class_reference_borrows import apply as apply_class_reference_borrows
    result=apply_class_reference_borrows(result,model)
    from .native_finite_depth_calls import apply as apply_finite_depth
    result=apply_finite_depth(result,model)
    from .native_single_execution_metadata import apply as apply_single_execution_metadata
    result=apply_single_execution_metadata(result,model)
    from .native_scope_views import apply as apply_scope_views
    result=apply_scope_views(result,model)
    from .native_scope_common import apply as apply_scope_common
    result=apply_scope_common(result,model)
    if prune_output:
        from .rust_pruning import prune_rust_source
        result=prune_rust_source(result)
    from .native_notices import retain_native_notices
    return retain_native_notices(result)
