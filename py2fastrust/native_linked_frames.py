"""Typed native frame emission for linked, independently scoped Python modules."""
import ast

from .native_module_linking import LinkedProgram,ModuleLinker,ModuleType,ClassReferenceType,UNIMPLEMENTED_IMPORT_METADATA,ANNOTATION_METADATA

# Imported lazily by the public API's linked path. These backend subclasses
# operate on original AST nodes; they never wrap user classes in fake ASTs.
from .native_classes import Model,Emitter,Cell,FunctionPlan,ClassUnsupported,Expression,shape,merge
from .native_class_globals import Namespace
from .native_aot_callables import CallableCells
from .native_linked_builtins import LinkedBuiltinBindings


class LinkedNamespace(Namespace):
    def fallback_runtime(self,emitter,name,kind):
        return self.model.callable_cells.linked_builtins.fallback_runtime(emitter,name,kind)

    def eligible(self,name):return name.startswith('\0module:')or super().eligible(name)


class LinkedCallableCells(CallableCells):
    def __init__(self,model):
        super().__init__(model)
        self.canonical_builtin_cells={}
        self.linked_builtins=LinkedBuiltinBindings(self)
        self.function_bindings.update(model.functions)
        self.used.update(self.definition(plan)for plan in model.functions.values())
        for name,plan in model.functions.items():
            model.namespace.active.add(name)
            model.namespace.refresh(name,plan.node)

    def stable_direct(self,plan,node,environment=None):return False

    def value(self,plan,node,environment):
        value=self.linked_builtins.value(plan,node,environment)
        return super().value(plan,node,environment)if value is None else value

    def read_emission(self,emitter,node):
        value=self.linked_builtins.read_emission(emitter,node)
        return super().read_emission(emitter,node)if value is None else value

    def candidate(self,plan,node,environment):
        if self.linked_builtins.candidate(plan,node,environment):return True
        if isinstance(node.func,ast.Attribute):
            receiver=self.model.module_linker.pure_cell(plan,node.func.value,environment)
            if receiver is not None and self.model.class_namespaces.descriptor_receiver(shape(receiver),self.model.resolved_name(plan,node.func)):return True
        value=self.model.module_linker.pure_cell(plan,node.func,environment)
        if value is not None and isinstance(value.root().tag,ClassReferenceType):return False
        if value is not None and isinstance(node.func,ast.Attribute):
            if getattr(shape(value),"_native_function_reference",False):return True
        if isinstance(node.func,ast.Attribute):
            receiver=self.receivers.get((plan.index,id(node)))
            if receiver is None:receiver=self.model.module_linker.pure_cell(plan,node.func.value,environment)
            if receiver is not None and self.model.module_linker.module_receiver_kinds(shape(receiver),node.func.attr):return True
        return super().candidate(plan,node,environment)

    def reference_code(self,emitter,plan):
        return f"ClassFunctionRef::F{self.definition(plan)}({self.model.module_linker.capture_context(emitter)})"

    def lambda_reference_code(self,emitter,plan,instance):
        return f"ClassFunctionRef::F{self.definition(plan)}({instance},{self.model.module_linker.capture_context(emitter)})"

    def call_pattern(self,definition):
        lexical="class_selected_environment,"if self.model.lexical.parent_scope(self.plans[definition])or isinstance(self.plans[definition].node,ast.Lambda)else""
        return f"ClassFunctionRef::F{definition}({lexical}class_defining_module)"

    def reference_pattern(self,definition):return f"ClassFunctionRef::F{definition}(..)"

    def lexical_reference_code(self,emitter,plan,owner):
        from .native_function_instances import instanced,reference
        if instanced(self.model.lexical,plan):return f'ClassFunctionRef::F{self.definition(plan)}('+reference(self.model.lexical,emitter,plan,owner)+','+self.model.module_linker.capture_context(emitter)+')'
        return f"ClassFunctionRef::F{self.definition(plan)}(({owner}).clone(),{self.model.module_linker.capture_context(emitter)})"

    def call_context_setup(self,emitter,target):
        return self.model.module_linker.call_context(emitter,"class_defining_module")

    def runtime(self):
        definitions=sorted(self.used)
        if not definitions and not self.builtin_used and not self.member_used and not self.bound_methods.used:return ""
        bound_declarations,bound_variants,bound_equals,bound_identity=self.bound_methods.runtime_parts()
        variants=[];arms=[]
        for value in definitions:
            parent=self.model.lexical.parent_scope(self.plans[value])
            if isinstance(self.plans[value].node,ast.Lambda):
                variants.append(f"F{value}(Rc<{self.model.lambda_cells.payload_type(self.plans[value])}>,ClassModuleRef)")
                arms.append(f"(Self::F{value}(a,m),Self::F{value}(b,n))=>Rc::ptr_eq(a,b)&&Rc::ptr_eq(m,n)")
            elif parent:
                from .native_function_instances import instanced,reference_type
                if instanced(self.model.lexical,self.plans[value]):
                    variants.append(f'F{value}('+reference_type(self.model.lexical,self.plans[value])+',ClassModuleRef)')
                    arms.append(f'(Self::F{value}(a,m),Self::F{value}(b,n))=>Rc::ptr_eq(&a.data,&b.data)&&Rc::ptr_eq(&a.environment,&b.environment)&&Rc::ptr_eq(m,n)')
                else:
                    variants.append(f"F{value}(Rc<{self.model.lexical.environment_type(parent)}>,ClassModuleRef)")
                    arms.append(f"(Self::F{value}(a,m),Self::F{value}(b,n))=>Rc::ptr_eq(a,b)&&Rc::ptr_eq(m,n)")
            else:
                variants.append(f"F{value}(ClassModuleRef)")
                arms.append(f"(Self::F{value}(a),Self::F{value}(b))=>Rc::ptr_eq(a,b)")
        native_variants=["B_"+identity.name for identity in sorted(self.builtin_used,key=lambda item:item.name)]+["M_"+identity.module+"_"+identity.name for identity in sorted(self.member_used,key=lambda item:(item.module,item.name))]
        variants.extend(bound_variants)
        arms.extend(bound_equals)
        variants.extend(native_variants)
        arms.extend(f"(Self::{name},Self::{name})=>true"for name in native_variants)
        return (bound_declarations+"\n#[derive(Clone)]\nenum ClassFunctionRef{"+
                ",".join(variants)+"}\n"
                "impl PartialEq for ClassFunctionRef{fn eq(&self,other:&Self)->bool{match(self,other){"+','.join(arms)+",_=>false}}}\n"+bound_identity)


class LinkedModel(Model):
    def __init__(self,linked,filename,integer,string_mode):
        self.module_linker=ModuleLinker(linked)
        self.module_linker.model=self
        self.module_plans={}
        super().__init__(linked.unit.tree,filename,integer,linked.unit.native_imports,unit=linked.unit,string_mode=string_mode)

    def create_namespace(self):
        from .native_class_namespaces import ClassNamespaces
        self.class_namespaces=ClassNamespaces(self)
        return LinkedNamespace(self)

    def create_callable_cells(self):
        provider=LinkedCallableCells(self)
        from .native_linked_members import MathAdapter,SysAdapter
        provider.register_member_adapter('math',MathAdapter)
        provider.register_member_adapter('sys',SysAdapter)
        from .native_typing_aliases import TypingAdapter
        provider.register_member_adapter('typing',TypingAdapter)
        from .native_itertools import ItertoolsAdapter
        provider.register_member_adapter('itertools',ItertoolsAdapter)
        from .native_functools_reduce import FunctoolsAdapter
        provider.register_member_adapter('functools',FunctoolsAdapter)
        from .native_operator_binary import OperatorAdapter
        provider.register_member_adapter('operator',OperatorAdapter)
        from .native_frame_heapq import HeapAdapter
        provider.register_member_adapter('heapq',HeapAdapter)
        from .native_frame_bisect import BisectAdapter
        provider.register_member_adapter('bisect',BisectAdapter)
        from .native_class_counters import CollectionsAdapter
        provider.register_member_adapter('collections',CollectionsAdapter)
        return provider

    def builtin_identity(self,plan,node,environment):
        identity=super().builtin_identity(plan,node,environment)
        provider=getattr(self,'callable_cells',None)
        return identity if provider is None else provider.linked_builtins.identity(plan,node,identity)

    def emitter(self,plan):return LinkedEmitter(self,plan)

    def class_runtime_context(self,owner):
        return "class_definition:ClassClassRef","class_definition:ClassClassRef","class_definition:class_definition.clone()"

    def finish_runtime(self,source):return render_linked_runtime(self,source)

    def is_module_plan(self,plan):return plan in self.module_plans.values()or plan is self.module

    def iter_nodes(self):
        from .native_annotations import executable_nodes
        for unit in self.unit.executable_source_units:
            for node in executable_nodes(unit.tree):
                if id(node)in self.unit.node_ordinals:yield node


    def iter_bindings(self):return self.unit.iter_bindings(executable_only=True)

    def call_global_names(self,caller,callee,environment):
        return {binding.name for binding in self.unit.bindings
                if self.module_owner(binding.owner)and self.unit.unit_for_scope(binding.owner).name==callee.module_name
                and binding.role not in {"load","parameter"}}

    def discover(self):
        linker=self.module_linker
        for unit in self.unit.executable_source_units:
            if unit is self.unit.main:plan=self.module
            else:
                plan=FunctionPlan(unit.tree,len(self.plans),visible_definitions=set(),global_names=set())
                self.bind_plan_origin(plan,unit.tree)
                merge(plan.result,Cell("none"),unit.tree)
                self.plans.append(plan)
            self.module_plans[unit.name]=plan
            linker.modules[unit.name].initializer=plan
        for unit in self.unit.executable_source_units:
            for node in unit.tree.body:
                if isinstance(node,ast.ClassDef):
                    key=self.definition_name(node)
                    if key in self.classes or key in self.functions:raise ClassUnsupported(node)
                    owner=self.discover_class(node,key)
                    self.namespace.incoming.setdefault(key,{})[("class_definition",self.unit.ordinal(node))]=Cell(ClassReferenceType(owner.index))
                    self.namespace.active.add(key)
                elif isinstance(node,ast.FunctionDef):
                    key=self.definition_name(node)
                    if key in self.classes or key in self.functions:raise ClassUnsupported(node)
                    self.functions[key]=self.function(node)
        linker.seed_namespaces()

    def expression(self,plan,node,environment):
        from .native_typing_metadata import registry
        metadata=registry(self).analyze(plan,node,environment)
        if metadata is not None:return metadata
        if isinstance(node,ast.Name):
            value=self.class_namespaces.read_name(plan,node,environment)
            if value is not None:return value
        if isinstance(node,ast.Name)and node.id in ANNOTATION_METADATA:
            binding=self.unit.binding_for(node)
            if (binding is not None and self.module_owner(binding.owner)
                    and binding.name not in self.global_written_names
                    and binding.name not in self.namespace.incoming):
                raise ClassUnsupported(node,'this implicit lazy module annotation binding needs its deferred annotation object and defining-namespace evaluation protocol; explicit ordinary user bindings with this name remain supported',proof='implicit module annotation namespace')
        if isinstance(node,ast.Name)and node.id in UNIMPLEMENTED_IMPORT_METADATA:
            binding=self.unit.binding_for(node)
            if binding is not None and self.module_owner(binding.owner):
                raise ClassUnsupported(node,f"module metadata binding {node.id!r} needs its Python import-spec/namespace object representation; that protocol is not implemented on the linked native path")
        return super().expression(plan,node,environment)

    def attribute_value(self,plan,node,receiver,environment):
        if receiver.root().tag=='object':
            owner=self.classes[receiver.root().args[0]]
            member=self.class_namespaces.members.get((owner.index,self.resolved_name(plan,node)))
            if member is not None and member.plan is not None and member.descriptor!="function":
                value=self.class_namespaces.analyze_attribute(plan,node,receiver,environment)
                if value is not None:return value
        return super().attribute_value(plan,node,receiver,environment)

    def attribute_item(self,plan,node,receiver,environment):
        result=self.class_namespaces.analyze_attribute(plan,node,receiver,environment)
        if result is not None:return result
        if not self.module_linker.module_receiver_kinds(shape(receiver),node.attr):return None
        self.module_linker.attribute_receivers[(plan.index,id(node))]=self.cell_for_kind(shape(receiver))
        result=self.cell(plan,node)
        for kind in self.module_linker.module_choices(receiver):
            value=self.module_linker.export_cell(kind,node.attr,node)
            self.namespace.contribute(result,value,node,force=True)
        return self.remember(plan,node,result)

    def attribute_target(self,plan,node,receiver,value,environment):
        if self.class_namespaces.assign_attribute(plan,node,receiver,value,environment):return True
        if not self.module_linker.module_receiver_kinds(shape(receiver),node.attr):return False
        result=self.cell(plan,node)
        for kind in self.module_linker.module_choices(receiver):
            field=self.module_linker.assign_export(kind,node.attr,node,value)
            self.namespace.contribute(result,field,node,force=True)
        self.remember(plan,node,result)
        return True

    def subscript_item(self,plan,node,owner,index,environment):
        from .native_linked_namespaces import analyze_item
        return analyze_item(self,plan,node,owner,index,environment)

    def target(self,plan,node,value,environment):
        if isinstance(node,ast.Attribute):
            parent=self.unit.parents.get(id(node))
            if isinstance(parent,ast.AugAssign)and parent.target is node:
                receiver=self.module_linker.attribute_receivers.get((plan.index,id(node)))
                if receiver is not None and self.attribute_target(plan,node,receiver,value,environment):return
        return super().target(plan,node,value,environment)

    def bind_name(self,plan,node,value,environment):
        if self.class_namespaces.bind_name(plan,node,value,environment):return
        return super().bind_name(plan,node,value,environment)

    def import_statement(self,plan,node,environment):
        linker=self.module_linker
        if isinstance(node,ast.ImportFrom)and any(alias.name=='*'for alias in node.names):
            raise ClassUnsupported(node,"star imports need export enumeration, __all__ evaluation and conditional binding/builtin lookup for each imported name; that namespace protocol is not yet implemented on the linked native path")
        bindings=self.unit.import_bindings(node)
        linker.imports[(plan.index,id(node))]=bindings
        for binding in bindings:
            requested=linker.modules[binding.module]
            parts=binding.module.split('.')
            for i in range(1,len(parts)+1):
                target=linker.modules['.'.join(parts[:i])]
                if target.initializer is not None:self.activate_frame(plan,node,target.initializer,environment)
            if binding.exported_name is None:value=linker.alias_value(binding)
            else:
                for child in binding.children:
                    if child.rpartition('.')[2]==binding.exported_name:
                        target=linker.modules[child]
                        if target.initializer is not None:self.activate_frame(plan,node,target.initializer,environment)
                value=linker.export_cell(requested.kind,binding.exported_name,node)
            self.bind_name(plan,binding.node,value,environment)
            self.namespace.import_event(plan,binding.node,environment)
        return True

    def call(self,plan,node,environment):
        from .call_semantics import normalize_call,CallBindingError
        known=self.module_linker.pure_cell(plan,node.func,environment)
        if known is not None and known.root().tag is None and not self.final:
            self.expression(plan,node.func,environment)
            for argument in node.args:self.expression(plan,argument,environment)
            for argument in node.keywords:self.expression(plan,argument.value,environment)
            return self.cell(plan,node)
        if known is not None and isinstance(known.root().tag,ClassReferenceType):
            reference=self.expression(plan,node.func,environment)
            try:normalized=normalize_call(node)
            except CallBindingError as error:raise ClassUnsupported(node,str(error))from None
            arguments=[self.expression(plan,arg.expression,environment)for arg in normalized.positional]
            keywords=[(arg.name,self.expression(plan,arg.expression,environment))for arg in normalized.keywords]
            owner=next(owner for owner in self.classes.values()if owner.index==known.root().tag.definition)
            result=self.class_namespaces.named_tuples.analyze_call(plan,node,owner,arguments,keywords,environment)
            if result is not None:return result
            from .native_class_constructor_calls import analyze_invalid_direct
            invalid=analyze_invalid_direct(self,plan,node,owner,reference,normalized,arguments,keywords,environment)
            if invalid is not None:return invalid
            owner.used=True
            result=self.cell(plan,node,"object",(self.class_key(owner),))
            constructor=owner.methods.get('__init__')
            if constructor is not None:self.bind_call(plan,node,constructor,[result]+arguments,keywords,environment)
            elif arguments or keywords:raise ClassUnsupported(node)
            self.module_linker.class_calls[(plan.index,id(node))]=owner
            return self.remember(plan,node,result)
        return super().call(plan,node,environment)


class LinkedEmitter(Emitter):
    def __init__(self,model,plan):
        super().__init__(model,plan)
        # Numeric primitives use the same original source location as the
        # surrounding frame, including errors inside imported functions.
        self.numeric.scope_code=self.location_code

    def rust_leaf(self,value,recurse):
        from .native_typing_aliases import AnnotationAlias
        if isinstance(value,AnnotationAlias)or getattr(value,'_native_typing_metadata',False):return 'NativeTypingSymbol'
        if isinstance(value,ModuleType):return "ClassModuleRef"
        if isinstance(value,ClassReferenceType):return "ClassClassRef"
        return super().rust_leaf(value,recurse)

    def location_code(self):
        from .native import _string
        return f"({_string(self.plan.source_unit.filename)},{_string(getattr(self,'logical_scope',self.plan.scope))})"

    def prepare_call_context(self,callee,receiver,constructor,defining_module=None):
        from .native_classes import InstanceType
        if defining_module is not None:return f"let class_scope=class_scope.with_module({defining_module});"
        if receiver is not None and isinstance(receiver.kind,InstanceType):
            return f"let class_scope=class_scope.with_module({receiver.code}.borrow().class_definition.module.clone());"
        return ""

    def constructor_context_arguments(self,constructor,defining_class):
        if defining_class is None:raise ClassUnsupported(constructor.node,"a linked class call needs its captured defining class object")
        return [defining_class]

    def truth(self,value,node=None):
        from .native_typing_metadata import reject_observation
        reject_observation(value.kind,node or self.plan.node)
        if isinstance(value.kind,(ModuleType,ClassReferenceType)):return "true"
        return super().truth(value,node)

    def comparison(self,operator,left,right,node):
        from .native_typing_metadata import reject_observation
        reject_observation(left.kind,node);reject_observation(right.kind,node)
        from .native_unions import union_kind
        from .native import _Expression
        if union_kind(left.kind)or union_kind(right.kind):return super().comparison(operator,left,right,node)
        refs=(ModuleType,ClassReferenceType)
        if isinstance(left.kind,refs)or isinstance(right.kind,refs):
            if isinstance(operator,(ast.Eq,ast.NotEq,ast.Is,ast.IsNot)):
                equal=f"Rc::ptr_eq(&{left.code},&{right.code})"if type(left.kind)is type(right.kind)else"false"
                return f"!({equal})"if isinstance(operator,(ast.NotEq,ast.IsNot))else equal
            raise ClassUnsupported(node,"module/class reference ordering and containment need their corresponding Python protocols")
        return super().comparison(operator,left,right,node)

    def show(self,value,node=None,quoted=False):
        from .native_typing_metadata import reject_observation
        reject_observation(value.kind,node)
        from .native import _string
        if isinstance(value.kind,ModuleType):
            module=self.model.module_linker.by_number[value.kind.number]
            if module.origin=='namespace':text=f"<module {module.name!r} (namespace) from {list(map(str,module.search_paths))!r}>"
            elif module.native_adapter:
                if module.name not in {'sys','builtins'}:
                    raise ClassUnsupported(node,'displaying this standard module needs its target-runtime import specification and origin; the canonical native operation adapter does not establish those metadata values',proof='standard module import metadata')
                text=f"<module {module.name!r} (built-in)>"
            else:text=f"<module {module.name!r} from {module.filename!r}>"
            return _string(text)+'.to_owned()'
        if isinstance(value.kind,ClassReferenceType):
            owner=next(owner for owner in self.model.classes.values()if owner.index==value.kind.definition)
            return _string(f"<class '{owner.module_name}.{self.model.class_namespaces.qualname(owner)}'>")+'.to_owned()'
        return super().show(value,node,quoted)

    def expression(self,node):
        value=self.model.class_namespaces.named_tuples.emit_attribute(self,node)
        if value is not None:return value
        from .native_typing_metadata import registry
        metadata=registry(self.model).emit(self,node)
        if metadata is not None:return metadata
        if isinstance(node,ast.Name):
            value=self.model.class_namespaces.emit_name(self,node)
            if value is not None:return value
        if isinstance(node,ast.Attribute)and(self.plan.index,id(node))in self.model.class_namespaces.attribute_reads:
            before,receiver=self.capture(self.expression(node.value))
            value=self.model.class_namespaces.emit_attribute(self,node,receiver)
            return Expression("{"+before+value.code+"}",value.kind)
        if isinstance(node,ast.Subscript):
            from .native_linked_namespaces import emit_item
            value=emit_item(self,node)
            if value is not None:return value
        if isinstance(node,ast.Attribute):
            owner_kind=self.kind(node.value)
            from .native_types import alternatives
            if self.model.module_linker.module_receiver_kinds(owner_kind,node.attr):
                before,owner=self.capture(self.expression(node.value))
                from .native_unions import project,union_kind
                wanted=self.kind(node)
                def branch(kind,code):
                    if kind=='none':return self.missing_module_attribute(node,wanted)
                    module=self.model.module_linker.by_number[kind.number]
                    if module.native_adapter and module.name=="sys"and node.attr=="stdin":return '()'
                    value=self.export(Expression(code,kind),kind,node.attr,node)
                    return self.coerce(value,wanted,node)
                code=project(owner_kind,owner.code,branch)if union_kind(owner_kind)else branch(owner_kind,owner.code)
                return Expression("{"+before+code+"}",wanted)
        return super().expression(node)

    def reference(self,target):
        if isinstance(target,ast.Attribute):
            from .native_types import alternatives
            kind=self.kind(target.value)
            if self.model.class_namespaces.class_choices(kind):
                setup,owner=self.capture(self.expression(target.value))
                return setup,('class_namespace',owner,self.model.resolved_name(self.plan,target))
            if self.model.module_linker.module_receiver_kinds(kind,target.attr):
                setup,owner=self.capture(self.expression(target.value))
                return setup,('module',owner,target.attr)
        return super().reference(target)

    def load_reference(self,reference,node,kind=None):
        if reference[0]=='name':
            value=self.model.class_namespaces.emit_name(self,reference[1],kind)
            if value is not None:return value
        if reference[0]=='class_namespace':
            _,owner,name=reference
            return self.model.class_namespaces.emit_attribute(self,node,owner)
        if reference[0]!='module':return super().load_reference(reference,node,kind)
        _,owner,name=reference
        from .native_unions import project,union_kind
        wanted=kind or self.kind(node)
        def branch(choice,code):
            if choice=='none':return self.missing_module_attribute(node,wanted)
            return self.coerce(self.export(Expression(code,choice),choice,name,node),wanted,node)
        code=project(owner.kind,owner.code,branch)if union_kind(owner.kind)else branch(owner.kind,owner.code)
        return Expression(code,wanted)

    def store_reference(self,reference,value,node):
        if reference[0]=='class_namespace':
            from .native_unions import project,union_kind
            _,owner,name=reference
            def branch(kind,code):
                member=self.model.class_namespaces.member(self.model.class_namespaces.owners[kind.definition],name)
                return '{'+self.model.class_namespaces.emit_store(self,member,value,node,module=f'({code}).module')+'}'
            result=project(owner.kind,owner.code,branch)if union_kind(owner.kind)else branch(owner.kind,owner.code)
            return result+';'
        if reference[0]!='module':return super().store_reference(reference,value,node)
        _,owner,name=reference
        from .native_unions import project,union_kind
        def branch(kind,code):
            if kind=='none':return self.missing_module_attribute(node,'none',writing=True)
            module=self.model.module_linker.by_number[kind.number]
            key=self.model.unit.global_name(module.name,name)
            index=self.model.namespace.index(key)
            wanted=dict(self.model.namespace.fields())[key]
            from .native_globals_view import store
            mark=store(self,node,name=key)
            if mark:
                # The captured receiver can differ from this frame's module.
                mark=mark.replace('class_scope.globals',code)
            return '{'+f'{code}.borrow_mut().value_{index}=Some({self.coerce(value,wanted,node)});'+mark+'}'
        code=project(owner.kind,owner.code,branch)if union_kind(owner.kind)else branch(owner.kind,owner.code)
        return code+';'

    def missing_module_attribute(self,node,wanted,*,writing=False):
        from .native import _string
        message=f"AttributeError: 'NoneType' object has no attribute '{node.attr}'"
        if writing:message+=' and no __dict__ for setting new attributes'
        message=_string(message)
        return self.at(f'Err::<{self.rust_type(wanted)},String>({message}.into())',node)

    def export(self,owner,kind,name,node,*,importing=False):
        from .native import _string
        key=self.model.unit.global_name(self.model.module_linker.by_number[kind.number].name,name)
        index=self.model.namespace.index(key)
        wanted=dict(self.model.namespace.fields())[key]
        value=self.fresh()
        result=(f"{{let {value}={owner.code}.borrow().value_{index}.clone();"
                f"{value}.ok_or_else(||class_module_export_error(&{owner.code},{_string(name)},{_string(repr(name))},{str(importing).lower()}))}}")
        return Expression(self.at(result,node),wanted)

    def import_module(self,module,node):
        from .native_class_calls import call
        return call(self,f"class_import_{module.number}(class_scope.clone())",module.initializer,node)

    def emit_import(self,node):
        bindings=self.model.module_linker.imports[(self.plan.index,id(node))]
        linker=self.model.module_linker
        lines=[]
        for binding in bindings:
            parts=binding.module.split('.')
            target=None
            for index in range(1,len(parts)+1):
                module=linker.modules['.'.join(parts[:index])]
                temporary=self.fresh()
                lines.append(f"let {temporary}={self.import_module(module,node)};")
                if index==1:root=Expression(temporary,module.kind)
                if binding.exported_name is None and module.name==binding.bound_module:target=Expression(temporary,module.kind)
                if module.name==binding.module:loaded=Expression(temporary,module.kind)
            steps=linker.alias_steps.get(self.model.unit.ordinal(binding.node))
            if steps:
                target=root
                for name,result in steps:
                    before,owner=self.capture(target)
                    lines.append(before)
                    target=self.import_alias_step(owner,name,binding.node,shape(result))
            if binding.exported_name is not None:
                children=[linker.modules[child]for child in binding.children if child.rpartition('.')[2]==binding.exported_name]
                if children:
                    child=children[0]
                    key=self.model.unit.global_name(binding.module,binding.exported_name)
                    field=self.model.namespace.index(key)
                    wanted=dict(self.model.namespace.fields())[key]
                    value=self.fresh()
                    fallback=self.coerce(Expression(self.import_module(child,node),child.kind),wanted,node)
                    code=(f"{{let {value}={loaded.code}.borrow().value_{field}.clone();"
                          f"if let Some(value)={value}{{value}}else{{{fallback}}}}}")
                    target=Expression(code,wanted)
                else:target=self.export(loaded,loaded.kind,binding.exported_name,node,importing=True)
            before,target=self.capture(target)
            lines.append(before)
            lines.append(self.assign_name(binding.node,target))
            from .native_globals_view import store
            lines.append(store(self,binding.node))
        return "".join(lines)

    def import_alias_step(self,owner,name,node,wanted):
        """IMPORT_FROM reads current attributes before its cache-only fallback."""
        from .native import _string
        from .native_unions import project,union_kind
        linker=self.model.module_linker
        def branch(kind,code):
            module=linker.by_number[kind.number]
            child=linker.modules.get(module.name+'.'+name)
            if child is None:
                return self.coerce(self.export(Expression(code,kind),kind,name,node,importing=True),wanted,node)
            key=self.model.unit.global_name(module.name,name)
            field=self.model.namespace.index(key)
            stored=dict(self.model.namespace.fields())[key]
            value=self.fresh();cached=self.fresh()
            fallback=self.coerce(Expression('module',child.kind),stored,node)
            error=f'class_module_export_error(&{code},{_string(name)},{_string(repr(name))},true)'
            missing=self.at(f'Err::<{self.rust_type(stored)},String>({error})',node)
            result=(f'{{let {value}={code}.borrow().value_{field}.clone();'
                    f'if let Some(value)={value}{{value}}else{{let {cached}={{class_scope.modules.borrow()[{child.number}].clone()}};'
                    f'if let Some(module)={cached}{{{fallback}}}else{{{missing}}}}}}}')
            return self.coerce(Expression(result,stored),wanted,node)
        code=project(owner.kind,owner.code,branch)if union_kind(owner.kind)else branch(owner.kind,owner.code)
        return Expression(code,wanted)

    def call(self,node):
        record=self.model.class_namespaces.named_tuples.emit_call(self,node)
        if record is not None:return record
        owner=self.model.module_linker.class_calls.get((self.plan.index,id(node)))
        if owner is not None:
            before,reference=self.capture(self.expression(node.func))
            result=self.call_user(node,owner.methods.get('__init__'),constructor=owner,
                defining_module=f"{reference.code}.module.clone()",defining_class=f"{reference.code}.clone()")
            return Expression("{"+before+result.code+"}",result.kind)
        return super().call(node)

    def statement(self,node):
        result=self.model.class_namespaces.emit_prepare_definition(self,node)+super().statement(node)
        result+=self.model.class_namespaces.emit_definition(self,node)
        if isinstance(node,ast.ClassDef):
            key=self.model.definition_name(node)
            owner=self.model.classes[key]
            index=self.model.namespace.index(key)
            created=self.fresh()
            value=f"Rc::new(ClassClassReference{{definition:{owner.index},module:class_scope.globals.clone()}})"
            wanted=dict(self.model.namespace.fields())[key]
            stored=self.coerce(Expression(created+'.clone()',ClassReferenceType(owner.index)),wanted,node)
            return result+f"let {created}={value};class_scope.globals.borrow_mut().value_{index}=Some({stored});"+self.model.class_namespaces.named_tuples.emit_retain_definition(self,node,owner,created)
        return result

    def assign_name(self,target,value):
        stored=self.model.class_namespaces.emit_assign_name(self,target,value)
        return super().assign_name(target,value)if stored is None else stored


def render_linked_runtime(model,source):
    """Render typed module cache/context support around shared native helpers."""
    from .native import _string
    from .native_class_calls import synchronous
    linker=model.module_linker
    emitter=model.emitter(model.module)
    fields=model.namespace.fields()
    defaults=model.namespace.default_fields()
    initialized=','.join(f'{prefix}_{index}:None'for prefix,items in(('value',fields),('default',defaults))for index in range(len(items)))
    if model.namespace.globals_observed:
        namespace_names,_=linker.namespace_names()
        initialized+=(','if initialized else'')+'present:['+','.join('false'for _ in namespace_names)+']'
    assert source.count('struct ClassGlobals{')==1
    source=source.replace('struct ClassGlobals{',"struct ClassGlobals{class_module_id:usize,class_module_status:u8,class_pending_children:Vec<&'static str>,",1)
    old='globals:Rc::new(RefCell::new(ClassGlobals{'+initialized+'}))'
    assert source.count(old)==1
    source=source.replace(old,'globals:class_globals,modules:class_modules',1)
    old='globals: Rc<RefCell<ClassGlobals>> }'
    assert source.count(old)==1
    source=source.replace(old,'globals: Rc<RefCell<ClassGlobals>>, modules: Rc<RefCell<Vec<Option<ClassModuleRef>>>> }',1)
    old='impl ClassScope {\n    fn new() -> Self {\n        Self {'
    assert source.count(old)==1
    source=source.replace(old,'impl ClassScope {\n    fn new() -> Self {\n        let class_globals=class_module_globals(0);\n'
        f'        let class_modules=Rc::new(RefCell::new(vec![None;{len(linker.modules)}]));\n'
        '        class_modules.borrow_mut()[0]=Some(class_globals.clone());\n'+model.callable_cells.linked_builtins.initialize_runtime()+ '        Self {',1)
    # A location is carried on every existing native error/call frame. The
    # original single-unit renderer and its helper signatures stay untouched.
    source=source.replace("function: &'static str, frames: Vec<(usize, &'static str)>",
                          'function: ClassLocation, frames: Vec<(usize, ClassLocation)>')
    source=source.replace("function: &'static str) -> Result<T, NativeError>",
                          'function: ClassLocation) -> Result<T, NativeError>')
    source=source.replace("caller:&'static str",'caller:ClassLocation').replace("caller: &'static str",'caller:ClassLocation')
    source=source.replace(f'{_string(model.filename)},line,function);','function.0,line,function.1);')
    source=source.replace(f'{_string(model.filename)},error.line,error.function,error.message);',
                          'error.function.0,error.line,error.function.1,error.message);')
    implicit={module.number:[]for module in linker.modules.values()}
    if model.namespace.globals_observed:
        for module in linker.modules.values():
            for key in sorted(linker.namespace_initial_names(module)):
                implicit[module.number].append(f'globals.borrow_mut().present[{namespace_names.index(key)}]=true;')
    for name,(number,value)in linker.implicit_values.items():
        index=model.namespace.index(name)
        kind=dict(fields)[name]
        raw=Expression('()','none')if value is None else Expression(f'NativeText::from({_string(value)})','str')
        code=emitter.coerce(raw,kind,model.tree)
        implicit[number].append(f'globals.borrow_mut().value_{index}=Some({code});')
    for name,(number,identity)in linker.implicit_members.items():
        index=model.namespace.index(name)
        kind=dict(fields)[name]
        raw=model.callable_cells.reference_expression(identity)
        code=emitter.coerce(raw,kind,model.tree)
        implicit[number].append(f'globals.borrow_mut().value_{index}=Some({code});')
    for name,(number,alias)in linker.annotation_aliases.items():
        index=model.namespace.index(name)
        raw=Expression('NativeTypingSymbol{case:0}',alias)
        code=emitter.coerce(raw,dict(fields)[name],model.tree)
        implicit[number].append(f'globals.borrow_mut().value_{index}=Some({code});')
    names=','.join(f'{module.number}=>({_string(module.name)},{_string(repr(module.name))},{_string(module.filename or "unknown location")},{_string(repr(module.filename or "unknown location"))},{str(module.possibly_shadowing).lower()},{str(module.shadowing_stdlib).lower()})'
                   for module in sorted(linker.modules.values(),key=lambda value:value.number))
    support=(["#[derive(Clone,Copy)] struct NativeTypingSymbol{case:usize}"]if linker.annotation_aliases or getattr(model,'typing_metadata',None)and model.typing_metadata.records else[])+['type ClassLocation=(&\'static str,&\'static str);',
             'type ClassModuleRef=Rc<RefCell<ClassGlobals>>;',
             'struct ClassClassReference{definition:usize,module:ClassModuleRef}',
             'type ClassClassRef=Rc<ClassClassReference>;',
             'impl ClassScope{fn with_module(&self,globals:ClassModuleRef)->Self{Self{control:self.control.clone(),io:self.io.clone(),globals,modules:self.modules.clone()}}}',
             'fn class_module_globals(module:usize)->ClassModuleRef{let globals=Rc::new(RefCell::new(ClassGlobals{class_module_id:module,class_module_status:if module==0{1}else{0},class_pending_children:Vec::new(),'+initialized+'}));match module{'+
             ','.join(f'{number}=>{{'+''.join(values)+'}'for number,values in sorted(implicit.items()))+',_=>unreachable!()}globals}',
             'fn class_module_export_error(globals:&ClassModuleRef,name:&str,name_repr:&str,importing:bool)->String{'
             'let (module,status,pending)={let values=globals.borrow();(values.class_module_id,values.class_module_status,values.class_pending_children.iter().any(|value|*value==name))};'
             'let (module,module_repr,file,file_repr,shadow,stdlib)=match module{'+names+',_=>unreachable!()};'
             'if importing{if stdlib{format!("ImportError: cannot import name {name_repr} from {module_repr} (consider renaming {file_repr} since it has the same name as the standard library module named {module_repr} and prevents importing that standard library module)")}else if status==0&&shadow{format!("ImportError: cannot import name {name_repr} from {module_repr} (consider renaming {file_repr} if it has the same name as a library you intended to import)")}else if status==0{format!("ImportError: cannot import name {name_repr} from partially initialized module {module_repr} (most likely due to a circular import) ({file})")}else{format!("ImportError: cannot import name {name_repr} from {module_repr} ({file})")}}'
             'else if stdlib{format!("AttributeError: module \'{module}\' has no attribute \'{name}\' (consider renaming \'{file}\' since it has the same name as the standard library module named \'{module}\' and prevents importing that standard library module)")}else if status==0&&shadow{format!("AttributeError: module \'{module}\' has no attribute \'{name}\' (consider renaming \'{file}\' if it has the same name as a library you intended to import)")}else if status==0{format!("AttributeError: partially initialized module \'{module}\' from \'{file}\' has no attribute \'{name}\' (most likely due to a circular import)")}else if pending{format!("AttributeError: cannot access submodule \'{name}\' of module \'{module}\' (most likely due to a circular import)")}else{format!("AttributeError: module \'{module}\' has no attribute \'{name}\'")}}']
    for module in sorted(linker.modules.values(),key=lambda value:value.number):
        if module.number==0:continue
        plan=module.initializer
        sync=synchronous(model,plan)
        body=(f'let cached={{class_scope.modules.borrow()[{module.number}].clone()}};'
              'if let Some(module)=cached{return Ok(module);}'
              f'let globals=class_module_globals({module.number});'
              f'class_scope.modules.borrow_mut()[{module.number}]=Some(globals.clone());')
        if plan is None:
            result='Ok(())'
        else:
            result=f'class_function_{plan.index}(class_scope.with_module(globals.clone()))'+(''if sync else'.await')
        parent,_,child=module.name.rpartition('.')
        if parent in linker.modules:
            parent_module=linker.modules[parent]
            body+=(f'let class_parent={{class_scope.modules.borrow()[{parent_module.number}].clone()}};'
                   f'if let Some(parent)=&class_parent{{parent.borrow_mut().class_pending_children.push({_string(child)});}}')
        body+='let result:ClassResult<()>= '+result+';'
        if parent in linker.modules:
            body+='if let Some(parent)=class_parent{parent.borrow_mut().class_pending_children.pop();}'
        body+='match result{Ok(())=>{globals.borrow_mut().class_module_status=1;'

        parent,_,child=module.name.rpartition('.')
        if parent in linker.modules:
            parent_module=linker.modules[parent]
            key=model.unit.global_name(parent,child)
            index=model.namespace.index(key)
            kind=dict(fields)[key]
            value=emitter.coerce(Expression('globals.clone()',module.kind),kind,model.tree)
            body+=(f'let parent={{class_scope.modules.borrow()[{parent_module.number}].clone()}};'
                   f'if let Some(parent)=parent{{parent.borrow_mut().value_{index}=Some({value});}}')
            if model.namespace.globals_observed:
                body+=f'if let Some(parent)={{class_scope.modules.borrow()[{parent_module.number}].clone()}}{{parent.borrow_mut().present[{namespace_names.index(key)}]=true;}}'
        body+=('Ok(globals)},Err(error)=>{globals.borrow_mut().class_module_status=2;'
               f'let matching=class_scope.modules.borrow()[{module.number}].as_ref().is_some_and(|current|Rc::ptr_eq(current,&globals));'
               f'if matching{{class_scope.modules.borrow_mut()[{module.number}]=None;}}Err(error)}}}}')
        if sync:support.append(f'fn class_import_{module.number}(class_scope:ClassScope)->ClassResult<ClassModuleRef>{{{body}}}')
        else:support.append(f'fn class_import_{module.number}(class_scope:ClassScope)->ClassFuture<ClassModuleRef>{{Box::pin(async move{{{body}}})}}')
    from .native_math_calls import helpers as math_helpers
    support.append(math_helpers(model.integer,getattr(model,'native_math_functions',())))
    from .native_frame_heapq import runtime as heap_runtime
    support.append(heap_runtime(model))
    from .native_frame_bisect import runtime as bisect_runtime
    support.append(bisect_runtime(model))
    return source+'\n'+'\n'.join(support)


def generate_linked(program,integer,*,prune_output=True,diagnostic_out=None,string_mode='ascii'):
    from .native_classes import try_generate_classes
    from .frontend import native_namespace_diagnostic
    from .diagnostics import Diagnostic
    for unit in program.units:
        namespace_error=native_namespace_diagnostic(unit)
        if namespace_error is not None:
            if diagnostic_out is not None:diagnostic_out.append(namespace_error)
            return None
        for binding in unit.bindings:
            if (unit.is_module_scope(binding.owner)and binding.role not in {'load','parameter'}
                    and binding.name in UNIMPLEMENTED_IMPORT_METADATA|{'__package__'}):
                node=unit.nodes[binding.node]
                if diagnostic_out is not None:diagnostic_out.append(Diagnostic(
                    f"changing import metadata binding {binding.name!r} needs dynamic module-spec/relative-import resolution, which is not implemented on the linked native path",unit.filename,node.line,node.column,'E006'))
                return None
    linked=LinkedProgram.from_program(program)
    factory=lambda tree,filename,integer,trusted_imports,**kwargs:LinkedModel(linked,filename,integer,kwargs['string_mode'])
    return try_generate_classes(program.main.source,program.main.filename,integer,unit=linked.unit,
        prune_output=prune_output,diagnostic_out=diagnostic_out,string_mode=string_mode,model_factory=factory)
