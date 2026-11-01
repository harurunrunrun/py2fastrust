"""Link official source units without copying or rewriting their Python ASTs.

The metadata view gives node/scope identities a program-wide address space.
Original source units remain available for signatures, source locations and
the defining namespace of functions, classes and closures.
"""
from __future__ import annotations

import ast
import builtins
import sys
from pathlib import Path
from dataclasses import dataclass,replace
from types import MappingProxyType

from .frontend import Binding,Symbol


_TOKENS=(ast.operator,ast.unaryop,ast.boolop,ast.cmpop,ast.expr_context)
_MODULE_INITIAL_NAMES=frozenset({'__name__','__doc__','__package__','__loader__','__spec__','__file__','__cached__','__builtins__','__annotations__','__path__'})
_DEFAULT_BUILTINS=(frozenset(vars(builtins))|{"__debug__"})-_MODULE_INITIAL_NAMES
UNIMPLEMENTED_IMPORT_METADATA=frozenset({'__spec__','__loader__','__cached__','__path__'})
ANNOTATION_METADATA=frozenset({'__annotations__','__annotate__'})


class QualifiedName(str):
    """An internal binding key retaining its original diagnostic spelling."""
    def __new__(cls,value,module,name):
        result=str.__new__(cls,value)
        result.module_name=module
        result.python_name=name
        result.display_name=name if module=='__main__'else module+'.'+name
        return result


@dataclass(frozen=True)
class BindingIdentity:
    module: str
    owner: int
    name: str


@dataclass(frozen=True)
class ImportBinding:
    """One import result bound to its actual lexical destination."""
    node: ast.alias
    name: str
    module: str
    exported_name: str|None
    children: tuple[str,...]=()
    bound_module: str|None=None


@dataclass(frozen=True)
class LinkedProgram:
    program: object
    unit: object

    @classmethod
    def from_program(cls,program):return cls(program,LinkedUnit(program))


class LinkedUnit:
    """Read-only metadata for original AST roots in separate Python modules.

    ``tree`` is deliberately only the original main AST. Cross-unit consumers
    must use ``source_units`` / ``iter_nodes`` rather than concatenate ASTs.
    Operator/context singletons have no unique source identity and are omitted
    from that source-node iterator; operators remain on their original nodes.
    """
    def __init__(self,program):
        self.program=program
        self.main=program.main
        self.source_units=tuple(program.units)
        from .module_catalog import VENDORED_MODULES
        self.native_adapter_modules=frozenset(module.name for module in program.modules
            if module.origin=='builtin'or module.origin=='vendored'and module.name in VENDORED_MODULES
            and module.name in program.native_imports)
        self.executable_source_units=tuple(unit for unit in self.source_units if unit.name not in self.native_adapter_modules)
        self.source=self.main.source
        self.filename=self.main.filename
        self.name=self.main.name
        self.package=self.main.package
        self.tree=self.main.tree
        self.table=self.main.table
        self.future_flags=self.main.future_flags
        self.native_imports=self.main.native_imports
        self._unit_numbers={unit.name:i for i,unit in enumerate(self.source_units)}
        self.module_numbers=dict(self._unit_numbers)
        for module in program.modules:
            if module.name not in self.module_numbers:self.module_numbers[module.name]=len(self.module_numbers)
        self._units_by_name={unit.name:unit for unit in self.source_units}
        self._node_units={}
        self._scope_units={}
        self._display_names={}
        self._raw_bindings={}
        self._binding_by_node={}
        self._source_nodes=[]
        self.parents={id(child):parent for unit in self.source_units for parent in ast.walk(unit.tree)
                      for child in ast.iter_child_nodes(parent)if not isinstance(child,_TOKENS)}
        ordinals={};definitions={};names={};signatures={};scopes=[];nodes=[];bindings=[];imports=[];roots={}
        self._offsets={}
        node_offset=scope_offset=0
        for unit in self.source_units:
            self._offsets[unit.name]=(node_offset,scope_offset)
            roots[unit.name]=scope_offset
            module_writes={binding.name for binding in unit.bindings
                           if unit.scopes[binding.owner].kind=="module" and binding.role not in {"load","parameter"}}
            raw_bindings={binding.node:binding for binding in unit.bindings}
            for node in ast.walk(unit.tree):
                if isinstance(node,_TOKENS):continue
                if id(node)in self._node_units:
                    raise ValueError("a source AST node belongs to more than one source unit")
                self._node_units[id(node)]=unit
                self._source_nodes.append(node)
                ordinals[id(node)]=node_offset+unit.ordinal(node)
                binding=raw_bindings.get(unit.ordinal(node))
                if binding is not None:self._raw_bindings[id(node)]=binding
                try:raw=unit.name_for(node)
                except KeyError:
                    if binding is None:continue
                    raw=binding.name
                if binding is not None and unit.scopes[binding.owner].kind=="module":
                    raw=self._global_name(unit,raw,module_writes)
                names[id(node)]=raw
            for scope in unit.scopes:
                self._scope_units[scope_offset+scope.ordinal]=unit
                symbols=tuple(Symbol(self._global_name(unit,value.name,module_writes),value.flags)
                              if scope.kind=="module"or value.has("global")else value
                              for value in scope.symbols)
                scopes.append(replace(scope,ordinal=scope.ordinal+scope_offset,
                    parent=None if scope.parent is None else scope.parent+scope_offset,
                    children=tuple(value+scope_offset for value in scope.children),symbols=symbols))
            for node in unit.nodes:
                nodes.append(replace(node,ordinal=node.ordinal+node_offset,scope=node.scope+scope_offset))
            for binding in unit.bindings:
                name=self._global_name(unit,binding.name,module_writes)if unit.scopes[binding.owner].kind=="module"else binding.name
                linked=Binding(name,binding.role,binding.scope+scope_offset,binding.owner+scope_offset,binding.node+node_offset)
                bindings.append(linked)
                self._binding_by_node[linked.node]=linked
            imports.extend(replace(item,node=item.node+node_offset)for item in unit.imports)
            definitions.update({identity:value+scope_offset for identity,value in unit.definition_scopes.items()})
            signatures.update(unit.function_signatures)
            node_offset+=len(unit.nodes)
            scope_offset+=len(unit.scopes)
        self.scopes=tuple(scopes)
        self.nodes=tuple(nodes)
        self.bindings=tuple(bindings)
        self.imports=tuple(imports)
        self.module_roots=MappingProxyType(roots)
        self.node_ordinals=MappingProxyType(ordinals)
        self.definition_scopes=MappingProxyType(definitions)
        self.resolved_names=MappingProxyType(names)
        self.function_signatures=MappingProxyType(signatures)

    def _global_name(self,unit,name,writes):
        # A genuinely unshadowed builtin remains a builtin lookup. Every other
        # global name belongs to one module, including unbound names. A NUL
        # prefix cannot collide with any Python identifier in a local scope.
        if name in _DEFAULT_BUILTINS and name not in writes:return name
        result=QualifiedName(f"\0module:{self.module_numbers[unit.name]}:{name}",unit.name,name)
        self._display_names[result]=name
        return result

    def global_name(self,module,name):
        result=QualifiedName(f"\0module:{self.module_numbers[module]}:{name}",module,name)
        self._display_names[result]=name
        return result

    def display_name(self,name):return self._display_names.get(name,name)

    def ordinal(self,node):return self.node_ordinals[id(node)]

    def original_unit(self,node):return self._node_units[id(node)]

    def original_ordinal(self,node):return self.original_unit(node).ordinal(node)

    def definition_key(self,node):return self.original_unit(node).name,self.original_ordinal(node)

    def is_module_scope(self,scope_id):return self.scopes[scope_id].kind=="module"

    def unit_for_scope(self,scope_id):return self._scope_units[scope_id]

    def scope_for(self,node):
        unit=self.original_unit(node)
        if node is unit.tree:return self.scopes[self.module_roots[unit.name]]
        return self.scopes[self.definition_scopes[id(node)]]

    def name_for(self,node):return self.resolved_names[id(node)]

    def signature_for(self,node):return self.function_signatures[id(node)]

    def binding_for(self,node):return self._binding_by_node.get(self.ordinal(node))

    def binding_identity(self,node):
        binding=self.binding_for(node)
        if binding is None:return None
        owner_unit=self.unit_for_scope(binding.owner)
        return BindingIdentity(owner_unit.name,binding.owner,self.display_name(binding.name))

    def iter_nodes(self,*,executable_only=False):
        if not executable_only:return iter(self._source_nodes)
        return (node for node in self._source_nodes if self.original_unit(node).name not in self.native_adapter_modules)

    def iter_bindings(self,*,executable_only=False):
        if not executable_only:return iter(self.bindings)
        return (binding for binding in self.bindings if self.unit_for_scope(binding.scope).name not in self.native_adapter_modules)

    def check_identity(self,source,filename):self.main.check_identity(source,filename)

    def import_bindings(self,node):
        unit=self.original_unit(node)
        records=[item for item in unit.imports if item.node==unit.ordinal(node)]
        if isinstance(node,ast.Import):
            if len(records)!=len(node.names):raise ValueError("resolved import record count does not match source")
            return tuple(ImportBinding(alias,self.name_for(alias),record.module,None,
                                       bound_module=record.module if alias.asname else record.module.split('.')[0])
                         for alias,record in zip(node.names,records))
        if isinstance(node,ast.ImportFrom):
            if len(records)!=1:raise ValueError("from import has no unique resolved import record")
            record=records[0]
            return tuple(ImportBinding(alias,self.name_for(alias),record.module,alias.name,record.children)for alias in node.names)
        raise TypeError("expected an import statement")


@dataclass(frozen=True)
class ModuleType:
    number: int
    _native_reference_cloneable=True
    _native_stored_reference=True

    @property
    def _native_kind_tag(self):return f"linked_module_{self.number}"


@dataclass(frozen=True)
class ClassReferenceType:
    definition: int
    _native_reference_cloneable=True
    _native_stored_reference=True

    @property
    def _native_kind_tag(self):return f"linked_class_{self.definition}"


@dataclass
class ModulePlan:
    name: str
    number: int
    source_unit: object
    origin: str
    package: bool
    filename: str|None
    initializer: object=None
    native_adapter: bool=False
    possibly_shadowing: bool=False
    shadowing_stdlib: bool=False
    search_paths: tuple=()

    @property
    def kind(self):return ModuleType(self.number)


class ModuleLinker:
    context_type="ClassModuleRef"
    def __init__(self,linked):
        self.linked=linked
        self.unit=linked.unit
        self.modules={}
        metadata={module.name:module for module in linked.program.modules}
        units={unit.name:unit for unit in self.unit.source_units}
        for name,number in self.unit.module_numbers.items():
            source=None if name in self.unit.native_adapter_modules else units.get(name)
            record=metadata.get(name)
            self.modules[name]=ModulePlan(name,number,source,
                record.origin if record is not None else"main",
                record.package if record is not None else source.package,
                record.filename if record is not None else source.filename,
                native_adapter=name in self.unit.native_adapter_modules)
            module=self.modules[name]
            if module.origin=='user'and module.filename is not None:
                origin=Path(module.filename)
                directory=origin.parent.parent if origin.name=='__init__.py'else origin.parent
                module.possibly_shadowing=directory.resolve()==Path(self.unit.filename).resolve().parent
                module.shadowing_stdlib=module.possibly_shadowing and name in sys.stdlib_module_names
            if record is not None:module.search_paths=record.search_paths
        self.by_number={module.number:module for module in self.modules.values()}
        self.class_calls={}
        self.attribute_receivers={}
        self.globals_items={}
        self.imports={}
        self.alias_steps={}
        self.implicit_values={}
        self.implicit_members={}
        self.model=None

    @staticmethod
    def capture_context(emitter):return "class_scope.globals.clone()"

    @staticmethod
    def call_context(emitter,context):return f"let class_scope=class_scope.with_module({context});"

    def pure_cell(self,plan,node,environment):
        """Read solved descriptors without evaluating an expression's effects."""
        from .native_classes import Cell,shape
        from .native_types import union_type
        if isinstance(node,ast.Name):
            name=self.model.resolved_name(plan,node)
            if name in environment:return environment[name]
            values=self.model.namespace.incoming.get(name,{})
            known=[shape(value)for value in values.values()if shape(value)is not None]
            if known:return self.model.cell_for_kind(union_type(*known))
        if isinstance(node,ast.Attribute):
            receiver=self.pure_cell(plan,node.value,environment)
            if receiver is not None and self.module_receiver_kinds(shape(receiver),node.attr):
                choices=[shape(self.export_cell(kind,node.attr,node,activate=False))for kind in self.module_choices(receiver)]
                if all(choice is not None for choice in choices):return self.model.cell_for_kind(union_type(*choices))
        return self.model.records.get((plan.index,id(node)))

    def export_cell(self,kind,name,node,*,activate=True):
        from .native_classes import Cell
        module=self.by_number[kind.number]
        if name in ANNOTATION_METADATA:
            from .native_classes import ClassUnsupported
            raise ClassUnsupported(node,f"module attribute {name!r} uses its lazy annotation descriptor, defining-namespace evaluation and cache protocol; that metadata-object protocol is not implemented on the linked native path",proof='module lazy annotation descriptor')
        if name in UNIMPLEMENTED_IMPORT_METADATA or name=='__dict__':
            from .native_classes import ClassUnsupported
            raise ClassUnsupported(node,f"module metadata attribute {name!r} needs its Python import-spec/namespace object representation; that protocol is not implemented on the linked native path")
        if module.native_adapter and module.name=="sys"and name=="stdin":return Cell("stdin")
        key=self.unit.global_name(module.name,name)
        if module.native_adapter and key not in self.model.namespace.incoming:
            self.seed_native_member(self.model.callable_cells,module,name)
        hook=self.unit.global_name(module.name,'__getattr__')
        if hook in self.model.namespace.incoming and name not in {'__name__','__package__','__doc__','__file__'}:
            from .native_classes import ClassUnsupported
            raise ClassUnsupported(node,"this module defines __getattr__; missing-export lookup needs its Python module fallback-call protocol, which is not implemented on the linked native path")
        if module.native_adapter and key not in self.model.namespace.incoming:
            from .native_classes import ClassUnsupported
            raise ClassUnsupported(node,f"the canonical builtin module {module.name!r} needs a typed adapter for member {name!r}; that member's native value/call protocol is not implemented")
        if activate:self.model.namespace.active.add(key)
        return self.model.namespace.refresh(key,node)

    @staticmethod
    def module_choices(value):
        from .native_classes import shape
        from .native_types import alternatives
        kind=shape(value)
        if kind is None:return ()
        choices=alternatives(kind)
        return tuple(choice for choice in choices if isinstance(choice,ModuleType))

    @staticmethod
    def module_receiver_kinds(kind,name):
        from .native_types import alternatives
        choices=alternatives(kind)
        # None has no user-replaceable attribute dictionary. Missing members
        # on its canonical builtin MRO have an ordinary AttributeError path.
        missing_none=all(name not in vars(owner)for owner in type(None).__mro__)
        if any(isinstance(choice,ModuleType)for choice in choices)and all(
                isinstance(choice,ModuleType)or choice=='none'and missing_none for choice in choices):return choices
        return ()

    def assign_export(self,kind,name,node,value):
        from .native_classes import ClassUnsupported
        module=self.by_number[kind.number]
        if name=='__annotate__':
            raise ClassUnsupported(node,'assigning module.__annotate__ requires its callable-or-None descriptor validation and lazy annotation cache protocol, which are not implemented on this native path',proof='module annotation descriptor assignment')
        if name in UNIMPLEMENTED_IMPORT_METADATA|{'__dict__','__package__'}:
            raise ClassUnsupported(node,'changing this module import-metadata attribute needs its dynamic namespace/import protocol',proof='module import metadata mutation')
        if module.native_adapter and module.name=='sys'and name in {'stdin','stdout','stderr'}:
            direction='read'if name=='stdin'else'write/flush'
            raise ClassUnsupported(node,f'replacing sys.{name} requires a stored stream-object identity and {direction} dispatch; the canonical standard-stream adapter does not implement replacement streams',proof='replaceable standard stream identity')
        key=self.unit.global_name(module.name,name)
        namespace=self.model.namespace
        namespace.incoming.setdefault(key,{})[("module_attribute_write",self.unit.ordinal(node))]=value
        namespace.active.add(key)
        return namespace.refresh(key,node)

    def alias_value(self,binding):
        from .native_classes import Cell,ClassUnsupported,shape
        parts=binding.module.split('.')
        if not binding.node.asname or len(parts)==1:return Cell(self.modules[binding.bound_module].kind)
        current=Cell(self.modules[parts[0]].kind)
        steps=[]
        for name in parts[1:]:
            from .native_types import alternatives
            if not all(isinstance(kind,ModuleType)for kind in alternatives(shape(current))):
                raise ClassUnsupported(binding.node,'this dotted import traverses a non-module replacement object; its IMPORT_FROM attribute/namespace protocol is not implemented',proof='dotted import alias current parent value')
            result=Cell()
            for kind in self.module_choices(current):
                value=self.export_cell(kind,name,binding.node)
                self.model.namespace.contribute(result,value,binding.node,force=True)
            steps.append((name,result))
            current=result
        self.alias_steps[self.unit.ordinal(binding.node)]=tuple(steps)
        return current

    def seed_namespaces(self):
        from .native_classes import Cell
        namespace=self.model.namespace
        for module in self.modules.values():
            values={'__name__':module.name,
                    '__package__':None if module.origin=="main"else module.name if module.package else module.name.rpartition('.')[0]}
            if module.source_unit is not None:values['__doc__']=ast.get_docstring(module.source_unit.tree,clean=False)
            elif module.origin=='namespace':values.update({'__doc__':None,'__file__':None})
            if module.source_unit is not None:values['__file__']=module.filename
            for name,value in values.items():
                key=self.unit.global_name(module.name,name)
                namespace.incoming.setdefault(key,{})[("module_implicit",module.number)]=Cell("none"if value is None else"str")
                namespace.active.add(key)
                self.implicit_values[key]=(module.number,value)
            parent,_,child=module.name.rpartition('.')
            if parent in self.modules:
                key=self.unit.global_name(parent,child)
                namespace.incoming.setdefault(key,{})[("module_child",module.number)]=Cell(module.kind)
                namespace.active.add(key)
        for name in namespace.active:namespace.refresh(name,self.model.tree)

    def seed_native_member(self,provider,module,name):
        """Populate a reachable trusted export with the common callable carrier."""
        from .native_module_calls import BuiltinRef
        from .references import BuiltinIdentity
        from .native_class_builtins import SUPPORTED
        if module.name=='builtins'and name in SUPPORTED:
            from .native_classes import Cell
            identity=BuiltinIdentity(name)
            provider.builtin_used.add(identity)
            value=provider.canonical_builtin_cells.setdefault(identity,Cell("function",(identity,)))
            self.model.namespace.flow_cells.add(value.root())
        else:
            adapter=provider.member_adapters.get(module.name)
            if adapter is None or name not in adapter.NAMES:return
            identity=BuiltinRef(module.name,name)
            value=provider.member_value(identity)
        key=self.unit.global_name(module.name,name)
        self.model.namespace.incoming.setdefault(key,{})[("native_member",identity)]=value
        self.model.namespace.active.add(key)
        self.model.namespace.refresh(key,self.model.tree)
        self.implicit_members[key]=(module.number,identity)

    def namespace_initial_names(self,module):
        names={'__name__','__doc__','__package__','__loader__','__spec__','__builtins__'}
        if module.filename is not None or module.origin=='namespace':names.update({'__file__','__cached__'})
        if module.package:names.add('__path__')
        return {self.unit.global_name(module.name,name)for name in names}

    def namespace_names(self):
        bound={binding.name for binding in self.unit.iter_bindings(executable_only=True)
               if self.model.module_owner(binding.owner)and binding.role not in {'load','parameter'}}
        initial=set().union(*(self.namespace_initial_names(module)for module in self.modules.values()))
        # Initialization depends on the actual module generation, not the
        # statically shared layout; its own initial bits are set by the factory.
        exports={name for name in self.model.namespace.incoming if isinstance(name,QualifiedName)}
        return sorted(initial|bound|exports|set(self.implicit_values)|set(self.implicit_members)),frozenset()



def needs_linking(program):
    from .module_catalog import VENDORED_MODULES
    # Builtin exports are snapshots of the same canonical namespace as its
    # module-object imports; source modules retain their own global shadows.
    builtin_namespace=any(module.name=='builtins'and module.origin=='builtin'for module in program.modules)
    return builtin_namespace or any(module.origin in {'user','namespace'}or module.origin=='vendored'and module.name not in VENDORED_MODULES
               for module in program.modules)



def generate_linked(program,integer,*,prune_output=True,diagnostic_out=None,string_mode='ascii'):
    from .native_linked_frames import generate_linked as generate
    return generate(program,integer,prune_output=prune_output,diagnostic_out=diagnostic_out,string_mode=string_mode)
