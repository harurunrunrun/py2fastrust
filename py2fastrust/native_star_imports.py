"""Closed module export schemas over original ASTs and actual native fields.

The original star node writes several real module bindings. It is not replaced
by synthetic Python statements or by execution of a submitted module.
"""
import ast
from dataclasses import dataclass


@dataclass(frozen=True)
class Exports:
    names:tuple
    explicit:bool=False
    items:tuple=()
    error:str|None=None


@dataclass(frozen=True)
class Star:
    node:object
    unit:object
    module:str


def is_star(node):
    return isinstance(node,ast.ImportFrom)and any(alias.name=='*'for alias in node.names)


class Catalog:
    def __init__(self,program):
        self.units={unit.name:unit for unit in program.units}
        self.modules={module.name:module for module in program.modules}
        self.stars={};self.exports={};self.writes={}
        for unit in program.units:
            self.writes[unit.name]=tuple(dict.fromkeys(binding.name for binding in unit.bindings
                if unit.scopes[binding.owner].kind=='module'and binding.role not in {'load','parameter'}and binding.name!='*'))
            records={item.node:item for item in unit.imports}
            for node in ast.walk(unit.tree):
                if is_star(node):self.stars[id(node)]=Star(node,unit,records[unit.ordinal(node)].module)
            self.exports[unit.name]=self.explicit_exports(unit)
        for module in program.modules:
            if module.name not in self.exports:
                from .native_math_exports import canonical, PUBLIC_NAMES
                if canonical(module):
                    self.writes[module.name]=PUBLIC_NAMES
                    self.exports[module.name]=Exports(PUBLIC_NAMES)
                else:
                    self.writes[module.name]=()
                    self.exports[module.name]=Exports((),error=('canonical module '+repr(module.name)+' needs its complete public export inventory for import *; that inventory is not implemented')if module.origin!='namespace'else None)
        candidates={name:list(names)for name,names in self.writes.items()}
        # Imported submodules become actual parent attributes only on success;
        # their optional native fields preserve that runtime presence below.
        for module in program.modules:
            parent,_,child=module.name.rpartition('.')
            if parent in candidates and child not in candidates[parent]:candidates[parent].append(child)
        while True:
            changed=False
            for star in self.stars.values():
                table=self.exports[star.module]
                names=table.names if table.explicit else tuple(name for name in candidates[star.module]if not name.startswith('_'))
                target=candidates[star.unit.name]
                for name in names:
                    if name not in target:target.append(name);changed=True
            if not changed:break
        for name,table in tuple(self.exports.items()):
            if not table.explicit:self.exports[name]=Exports(tuple(value for value in candidates[name]if not value.startswith('_')),error=table.error)
        self.module_writes={unit.name:tuple(dict.fromkeys(name for star in self.stars.values()if star.unit is unit for name in self.exports[star.module].names))for unit in program.units}

    @staticmethod
    def explicit_exports(unit):
        writes=[binding for binding in unit.bindings if binding.name=='__all__'
                and unit.scopes[binding.owner].kind=='module'and binding.role!='load']
        if not writes:return Exports(())
        reason='module '+repr(unit.name)+' has a computed, aliased or mutable __all__; import * needs its runtime export-sequence protocol, which is not implemented for that publication'
        if len(writes)!=1:return Exports((),error=reason)
        nodes={unit.ordinal(node):node for node in ast.walk(unit.tree)}
        parents={id(child):node for node in ast.walk(unit.tree)for child in ast.iter_child_nodes(node)}
        target=nodes[writes[0].node];statement=parents.get(id(target));value=None
        if isinstance(statement,ast.Assign)and len(statement.targets)==1 and statement.targets[0]is target:value=statement.value
        if isinstance(statement,ast.AnnAssign)and statement.target is target:value=statement.value
        if value is None or statement not in unit.tree.body:return Exports((),error=reason)
        if any(binding.name=='__all__'and binding.role=='load'and unit.scopes[binding.owner].kind=='module'for binding in unit.bindings):return Exports((),error=reason)
        try:literal=ast.literal_eval(value)
        except (ValueError,TypeError,SyntaxError):return Exports((),error=reason)
        if isinstance(literal,(str,bytes,list,tuple)):
            items=tuple(literal);names=tuple(dict.fromkeys(item for item in items if isinstance(item,str)))
            return Exports(names,True,items)
        if isinstance(literal,(dict,set)):
            return Exports((),error='module '+repr(unit.name)+' uses a mapping/set __all__; its indexed export-container protocol is not implemented')
        return Exports((),True,(),"TypeError: '"+type(literal).__name__+"' object does not support indexing")

    def table(self,node):return self.exports[self.stars[id(node)].module]

    def validate(self,node):
        from .native_classes import ClassUnsupported
        star=self.stars[id(node)];table=self.table(node)
        if table.error and not table.error.startswith('TypeError:'):
            raise ClassUnsupported(node,table.error,proof='closed original module export schema')
        module=self.modules.get(star.module)
        if module is not None and module.package and table.explicit and any(isinstance(item,str)and not item.isidentifier()for item in table.items):
            raise ClassUnsupported(node,'package __all__ contains a name outside the static identifier child-module schema; dotted/arbitrary package export-name lookup is not implemented',proof='package star export child-module identity')
        if '__all__'in table.names:
            raise ClassUnsupported(node,'importing __all__ itself needs a derived export schema for later star imports; that metadata propagation is not implemented',proof='star-imported export-sequence identity')
        unit=self.units.get(star.module)
        if unit is not None and any(binding.name=='__getattr__'and unit.scopes[binding.owner].kind=='module'and binding.role!='load'for binding in unit.bindings):
            raise ClassUnsupported(node,'module import * with __getattr__ needs its export-lookup callback protocol; that module hook is not implemented',proof='module star export attribute lookup')


def implicit_bindings(linked,unit,node_offset,scope_offset):
    from .frontend import Binding
    for star in linked.star_imports.stars.values():
        if star.unit is not unit:continue
        scope=unit.nodes[unit.ordinal(star.node)].scope+scope_offset
        for name in linked.star_imports.table(star.node).names:
            yield Binding(linked.global_name(unit.name,name),'import',scope,scope,node_offset+unit.ordinal(star.node.names[0]))


def analyze(model,plan,node,environment):
    if not is_star(node):return False
    from .native_classes import Cell
    catalog=model.unit.star_imports;catalog.validate(node)
    table=catalog.table(node);linker=model.module_linker;star=catalog.stars[id(node)];requested=linker.modules[star.module]
    from .native_math_exports import guard_observation
    guard_observation(model,node,requested)
    for i in range(1,len(star.module.split('.'))+1):
        target=linker.modules['.'.join(star.module.split('.')[:i])]
        if target.initializer is not None:model.activate_frame(plan,node,target.initializer,environment)
    bindings=model.unit.import_bindings(node);linker.imports[plan.index,id(node)]=bindings
    for child in dict.fromkeys(child for binding in bindings for child in binding.children):
        target=linker.modules[child]
        if target.initializer is not None:model.activate_frame(plan,node,target.initializer,environment)
    for binding in bindings:
        value=linker.export_cell(requested.kind,binding.exported_name,node,context=(plan,environment))
        name=binding.name;namespace=model.namespace
        namespace.incoming.setdefault(name,{})[('star_import',model.unit.ordinal(node),name)]=value
        namespace.active.add(name);namespace.refresh(name,node)
        point=model.cell(plan,node,identity=('star_import_binding',name))
        namespace.contribute(point,value,node,force=True)
        previous=environment.get(name);definite=name in environment.definite
        if not table.explicit and previous is not None:
            joined=namespace.join_values(previous,point,node,name,'star_import_presence')
            point=namespace.refresh(name,node)if joined is None else joined
        environment[name]=point
        if table.explicit or definite:environment.definite.add(name)
        else:environment.definite.discard(name)
        if table.explicit and plan.visible_definitions is not None:plan.visible_definitions.add(name)
    model.exceptions.require(node)
    return True


def emit(emitter,node):
    if not is_star(node):return None
    from .native_classes import Expression
    from .native_globals_view import store
    from .native import _string
    linker=emitter.model.module_linker;catalog=emitter.model.unit.star_imports;table=catalog.table(node);star=catalog.stars[id(node)]
    code='';loaded=None
    for i in range(1,len(star.module.split('.'))+1):
        module=linker.modules['.'.join(star.module.split('.')[:i])];temporary=emitter.fresh()
        code+='let '+temporary+'='+emitter.import_module(module,node)+';';loaded=Expression(temporary,module.kind)
    module=linker.modules[star.module]
    if table.error:
        error=table.error.replace('does not support indexing','is not iterable')if module.package else table.error
        return code+emitter.at('Err::<(),String>('+_string(error)+'.to_owned())',node)+';'
    bindings={binding.exported_name:binding for binding in linker.imports[emitter.plan.index,id(node)]}
    fields=dict(emitter.model.namespace.fields())
    if module.package and table.explicit:
        # Importlib finishes the complete from-list before IMPORT_STAR writes
        # any importer name. Cached children do not republish a deleted attr.
        for name in table.items:
            if not isinstance(name,str):
                error='TypeError: Item in '+star.module+'.__all__ must be str, not '+type(name).__name__
                return code+emitter.at('Err::<(),String>('+_string(error)+'.to_owned())',node)+';'
            binding=bindings[name]
            for child_name in binding.children:
                if child_name.rpartition('.')[2]!=name:continue
                key=emitter.model.unit.global_name(star.module,name);field=emitter.model.namespace.index(key)
                missing=emitter.fresh()
                code+='let '+missing+'={'+loaded.code+'.borrow().value_'+str(field)+'.is_none()};'
                code+='if '+missing+'{let _='+emitter.import_module(linker.modules[child_name],node)+';}'
    for name in table.items if table.explicit else table.names:
        if not isinstance(name,str):
            error='TypeError: Item in '+star.module+'.__all__ must be str, not '+type(name).__name__
            code+=emitter.at('Err::<(),String>('+_string(error)+'.to_owned())',node)+';';break
        binding=bindings[name];destination=emitter.model.namespace.index(binding.name);wanted=fields[binding.name]
        if table.explicit:
            before,value=emitter.capture(emitter.export(loaded,loaded.kind,name,node,importing=False));code+=before
            code+='class_scope.globals.borrow_mut().value_'+str(destination)+'=Some('+emitter.coerce(value,wanted,node)+');'+store(emitter,node,name=binding.name)
        else:
            key=emitter.model.unit.global_name(star.module,name);source=emitter.model.namespace.index(key);value=emitter.fresh()
            raw=Expression(value,fields[key]);converted=emitter.coerce(raw,wanted,node)
            code+='if let Some('+value+')={let value='+loaded.code+'.borrow().value_'+str(source)+'.clone();value}{class_scope.globals.borrow_mut().value_'+str(destination)+'=Some('+converted+');'+store(emitter,node,name=binding.name)+'}'
    return code


def resolve_package_children(resolver,module,importer,node):
    """Resolve literal from-list children as metadata, never execute a module."""
    unit=resolver.units.get(module.name)
    if unit is None:return ()
    table=Catalog.explicit_exports(unit)
    if not table.explicit or table.error:return ()
    children=[]
    for name in table.items:
        if not isinstance(name,str):break
        if not name.isidentifier():continue
        child=module.name+'.'+name
        if resolver.find(child):resolver.load(child,importer,node);children.append(child)
    return tuple(children)


def guard_export_change(model,kind,name,node,*,writing=False):
    """An unchecked late export must not silently disappear from a star view."""
    from .native_classes import ClassUnsupported
    module=model.module_linker.by_number[kind.number]
    catalog=model.unit.star_imports
    if not any(star.module==module.name for star in catalog.stars.values()):return
    table=catalog.exports[module.name]
    if name=='__all__':
        raise ClassUnsupported(node,'observing or replacing __all__ through a module object invalidates this import * export-sequence certificate; runtime export-list mutation is not implemented',proof='original closed star export sequence')
    if writing and not table.explicit and name not in table.names and not name.startswith('_'):
        raise ClassUnsupported(node,'adding module export '+repr(name)+' needs an expanded star-import namespace schema; that dynamic module export publication is not implemented',proof='closed star export name set')
