"""Canonical mutable builtins namespace lookup for linked native modules."""
import ast


class LinkedBuiltinBindings:
    def __init__(self,provider):
        self.provider=provider
        self.model=provider.model
        module=self.model.module_linker.modules.get('builtins')
        self.module=module if module is not None and module.native_adapter else None
        self.sites={}

    def binding(self,plan,node):
        from .native_builtin_identities import names as builtin_value_names
        SUPPORTED=builtin_value_names()
        if self.module is None or not isinstance(node,ast.Name):return None
        provider=self.provider
        name=self.model.resolved_name(plan,node)
        if not self.model.module_owner(provider.owner(plan,node)):return None
        if self.model.lexical.field_for(node)is not None or self.model.lexical.function_for(node)is not None:return None
        spelling=provider.spelling(name)
        key=self.model.unit.global_name(self.module.name,spelling)
        if spelling not in SUPPORTED:
            if key not in self.model.namespace.incoming:return None
        if name in self.model.classes:
            if key in self.model.namespace.incoming:
                from .native_classes import ClassUnsupported
                raise ClassUnsupported(node,'this class-name binding can fall back to a mutable builtin namespace value; its finite class-object/value constructor carrier is not implemented',proof='class-name builtin fallback and constructor protocol')
            return None
        return name,spelling

    def identity(self,plan,node,identity):
        """Prove an intrinsic only while its canonical field has that identity."""
        from .references import BuiltinIdentity,UnknownReference
        from .native_classes import shape
        if not isinstance(identity,BuiltinIdentity):return identity
        binding=self.binding(plan,node)
        if binding is None:return identity
        _,spelling=binding
        key=self.model.unit.global_name(self.module.name,spelling)
        sources=self.model.namespace.incoming.get(key,{})
        for value in sources.values():
            kind=shape(value)
            if not getattr(kind,'_native_function_reference',False)or kind.targets!=(identity,):
                return UnknownReference(self.model.resolved_name(plan,node),'canonical builtins namespace binding may be replaced')
        return identity

    def candidate(self,plan,node,environment):
        binding=self.binding(plan,node.func)
        if binding is None:return False
        name,_=binding
        value=environment.get(name)
        if value is not None and value.root().tag in self.model.INTRINSICS:return False
        return True

    def value(self,plan,node,environment):
        binding=self.binding(plan,node)
        if binding is None:return None
        name,spelling=binding
        provider=self.provider
        if name in self.model.global_symbols:return None
        from .native_builtin_namespace_points import unsupported_initial
        from .native_builtin_identities import names as builtin_value_names
        if (unsupported_initial(self.model,self.module,spelling)
                and spelling not in builtin_value_names()
                and self.model.is_module_plan(plan)and name in environment
                and name in getattr(environment,'definite',())):
            # An existing definite module binding is selected before builtin
            # fallback; its supported payload needs no original builtin value.
            self.sites.pop((plan.index,id(node)),None)
            return None
        key=self.model.unit.global_name(self.module.name,spelling)
        linker=self.model.module_linker
        linker.seed_native_member(provider,self.module,spelling)
        builtin=linker.export_cell(self.module.kind,spelling,node,context=(plan,environment))
        stored=self.model.namespace.refresh(key,node)
        provider.builtin_cells[name]=stored
        provider.builtin_sites.pop((plan.index,id(node)),None)
        if name not in provider.mutable_names and name not in self.model.functions and name not in self.model.namespace.incoming:
            self.sites[(plan.index,id(node))]=key
            return builtin
        self.sites.pop((plan.index,id(node)),None)
        provider.fallback_names.add(name)
        self.model.namespace.incoming.setdefault(name,{})[("builtin",name)]=stored
        if name in self.model.functions:provider.function_bindings.add(name)
        schema=provider.require_binding(name,node)
        if self.model.is_module_plan(plan):
            if name not in environment:return schema
            point=environment[name]
            if name not in environment.definite:
                joined=self.model.namespace.join_values(point,builtin,node,name,"builtin_fallback")
                return schema if joined is None else joined
            return point
        return schema

    def load(self,name):
        from .native import _string
        index=self.model.namespace.index(name)
        error=_string("NameError: name '"+self.provider.spelling(name)+"' is not defined")
        return ("{let class_builtins={scope.modules.borrow()["+str(self.module.number)+"].clone().expect(\"canonical builtins namespace\")};"
                f"let class_value=class_builtins.borrow().value_{index}.clone();class_value.ok_or_else(||{error}.to_owned())"+"}")

    def read_emission(self,emitter,node):
        from .native_classes import Expression
        from .native_class_globals import narrow_binding
        key=self.sites.get((emitter.plan.index,id(node)))
        if key is None:return None
        stored=dict(self.model.namespace.fields())[key]
        loaded=emitter.at(self.load(key).replace('scope.modules','class_scope.modules'),node)
        return narrow_binding(emitter,node,stored,emitter.kind(node),loaded)

    def fallback_runtime(self,emitter,name,kind):
        from .native_classes import Expression,shape
        if self.module is None or name not in self.provider.builtin_cells:return None
        key=self.model.unit.global_name(self.module.name,self.provider.spelling(name))
        fallback=self.load(key)
        value=emitter.coerce(Expression('class_builtin',shape(self.provider.builtin_cells[name])),kind,self.model.tree)
        index=self.model.namespace.index(name)
        return (f"{{let class_value=scope.globals.borrow().value_{index}.clone();match class_value{{Some(value)=>Ok(value),"
                f"None=>({fallback}).map(|class_builtin|{value})}}}}")

    def initialize_runtime(self):
        if self.module is None:return ''
        number=self.module.number
        return (f'        let class_builtins=class_module_globals({number});\n'
                '        class_builtins.borrow_mut().class_module_status=1;\n'
                f'        class_modules.borrow_mut()[{number}]=Some(class_builtins);\n')
