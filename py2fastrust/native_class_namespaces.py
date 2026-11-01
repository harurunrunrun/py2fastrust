"""Typed class namespaces keyed by official definition and binding owners.

Class references capture the defining module. A module initialization executes
each admitted class definition once, so separate typed slots can represent its
namespace without a heterogeneous dictionary or a bytecode interpreter.
"""
import ast
from dataclasses import dataclass

from .native_module_linking import QualifiedName,ClassReferenceType


class ClassNamespaceName(QualifiedName):
    _native_class_namespace_field=True


@dataclass
class ClassMember:
    owner: object
    name: str
    key: object
    plan: object=None
    function_cell: object=None
    descriptor: str="function"
    observed: bool=False


class ClassNamespaces:
    @staticmethod
    def special_name(name):return name.startswith('__')and name.endswith('__')
    def __init__(self,model):
        self.model=model
        self.unit=model.unit
        self.bindings={binding.node:binding for binding in self.unit.bindings}
        self.owners={}
        self.scopes={}
        self.keys={}
        self.parents={}
        self.members={}
        self.name_reads={}
        self.attribute_reads={}
        self.instance_reads={}

    def key(self,owner,name):
        number=self.unit.module_numbers[owner.module_name]
        ordinal=self.unit.ordinal(owner.node)
        return ClassNamespaceName(f"\0module:{number}:\0class:{ordinal}:{name}",owner.module_name,name)

    def member(self,owner,name):
        identity=owner.index,name
        result=self.members.get(identity)
        if result is None:
            result=ClassMember(owner,name,self.key(owner,name))
            self.members[identity]=result
        return result

    def field(self,member,node):
        namespace=self.model.namespace
        namespace.incoming.setdefault(member.key,{})
        namespace.active.add(member.key)
        return namespace.refresh(member.key,node)

    def contribute(self,member,value,node,role="store"):
        self.model.namespace.incoming.setdefault(member.key,{})[(role,self.unit.ordinal(node))]=value
        return self.field(member,node)

    def register(self,owner,parent=None):
        self.owners[owner.index]=owner
        self.scopes[self.unit.scope_for(owner.node).ordinal]=owner
        self.keys[id(owner.node)]=self.model.class_key(owner)
        if parent is not None:self.parents[owner.index]=parent

    def nested_key(self,owner,node):
        name=self.model.resolved_name(owner.body_plan or self.model.module,node)
        result=self.member(owner,name).key
        self.keys[id(node)]=result
        return result

    def register_child(self,owner,node,child):
        from .native_classes import Cell
        member=self.member(owner,self.model.resolved_name(self.model.module,node))
        self.contribute(member,Cell(ClassReferenceType(child.index)),node,"class_definition")

    def receiver_kind(self,owner,node):
        from .native_class_descriptors import receiver_kind
        return receiver_kind(self,owner,node)

    def register_method(self,owner,name,plan):
        from .native_classes import Cell
        member=self.member(owner,name)
        member.plan=plan
        member.function_cell=Cell("function",(self.unit.ordinal(plan.node),))
        return member

    @staticmethod
    def class_statement(node):
        return isinstance(node,(ast.Assign,ast.AnnAssign,ast.AugAssign,ast.Delete,ast.Expr))

    def local_member(self,plan,node):
        binding=self.bindings.get(self.unit.ordinal(node))
        owner=self.scopes.get(binding.owner)if binding is not None else None
        if owner is None or plan.class_body is not owner:return None
        return self.member(owner,binding.name)

    def bind_name(self,plan,node,value,environment):
        member=self.local_member(plan,node)
        if member is None:return False
        if self.special_name(member.name):
            from .native_classes import ClassUnsupported
            raise ClassUnsupported(node,f"class-body metadata assignment {member.name!r} requires its compiler/metaclass namespace validation; that metadata protocol is not implemented",proof="class compiler metadata initialization and validation")
        self.contribute(member,value,node)
        environment[member.name]=value
        environment.definite.add(member.name)
        self.model.remember(plan,node,value)
        return True

    def fallback(self,owner,name,node):
        namespace=self.model.namespace
        key=self.unit.global_name(owner.module_name,name)
        if name in namespace.builtin_names and key not in self.model.module_linker.implicit_values:
            from .native_classes import ClassUnsupported
            raise ClassUnsupported(node,f"class-local name {name!r} may fall back to a module or builtin object; capturing this LOAD_NAME builtin fallback is not implemented",proof="definite module binding or captured builtin fallback for class-local lookup")
        namespace.incoming.setdefault(key,{})
        namespace.active.add(key)
        return key,namespace.refresh(key,node)

    def read_name(self,plan,node,environment):
        if(plan.class_body is not None and self.special_name(node.id)
                and node.id not in {'__name__','__file__','__package__','__cached__'}):
            from .native_classes import ClassUnsupported
            raise ClassUnsupported(node,f"class-body metadata reference {node.id!r} requires the compiler-initialized class namespace and its metadata lookup protocol; that protocol is not implemented",proof="class compiler metadata initialization and lookup")
        member=self.local_member(plan,node)
        if member is None:return None
        if member.plan is not None and member.descriptor!="function":
            from .native_classes import ClassUnsupported
            raise ClassUnsupported(node,"reading this descriptor as a bare class-body value needs its raw descriptor-object carrier; class and instance attribute binding are supported, but storing the undecorated classmethod descriptor is not implemented",proof="raw class-body descriptor object identity")
        self.field(member,node)
        if member.plan is not None:self.observe_method(member,node)
        local=environment.get(member.name)
        definite=member.name in getattr(environment,"definite",environment)
        fallback=None
        if local is None or not definite:
            key,value=self.fallback(member.owner,member.name,node)
            fallback=key
            if local is None:local=value
            else:
                joined=self.model.namespace.join_values(local,value,node,member.key,"class_name_fallback")
                if joined is not None:local=joined
        self.name_reads[(plan.index,id(node))]=(member,fallback)
        return self.model.remember(plan,node,local)

    def observe_method(self,member,node):
        member.observed=True
        provider=getattr(self.model,"callable_cells",None)
        if provider is not None:provider.used.add(provider.definition(member.plan))
        self.contribute(member,member.function_cell,member.plan.node,"method_definition")

    def definition_event(self,plan,node,environment):
        if plan.class_body is None:return
        owner=plan.class_body
        name=self.model.resolved_name(plan,node)
        member=self.member(owner,name)
        if isinstance(node,ast.ClassDef):
            from .native_classes import Cell
            child=self.model.classes[self.model.definition_name(node)]
            value=Cell(ClassReferenceType(child.index))
            self.contribute(member,value,node,"class_definition")
        else:
            from .native_class_descriptors import analyze_definition
            analyze_definition(self,plan,node,member,environment)
            value=member.function_cell
            if member.observed:self.observe_method(member,node)
        environment[name]=value
        environment.definite.add(name)

    def prepare_definition(self,plan,node,environment):
        if plan.class_body is None or not isinstance(node,ast.FunctionDef):return
        from .native_class_descriptors import prepare_definition
        member=self.member(plan.class_body,self.model.resolved_name(plan,node))
        prepare_definition(self,plan,node,member,environment)

    def emit_prepare_definition(self,emitter,node):
        if emitter.plan.class_body is None or not isinstance(node,ast.FunctionDef):return ""
        from .native_class_descriptors import emit_prepare_definition
        member=self.member(emitter.plan.class_body,self.model.resolved_name(emitter.plan,node))
        return emit_prepare_definition(self,emitter,node,member)

    def descriptor_receiver(self,kind,name):
        from .native_classes import InstanceType
        if isinstance(kind,InstanceType):owners=(self.model.classes[kind.name],)
        else:owners=tuple(self.owners[choice.definition]for choice in self.class_choices(kind))
        return any((owner.index,name)in self.members and self.members[(owner.index,name)].plan is not None and self.members[(owner.index,name)].descriptor!="function"for owner in owners)

    def class_choices(self,kind):
        from .native_types import alternatives
        choices=alternatives(kind)
        return choices if choices and all(isinstance(choice,ClassReferenceType)for choice in choices)else ()

    def pure_attribute(self,value,name,node):
        from .native_classes import shape,Cell
        choices=self.class_choices(shape(value))
        if not choices:return None
        result=Cell()
        for choice in choices:
            member=self.member(self.owners[choice.definition],name)
            value=member.function_cell if member.plan is not None else self.field(member,node)
            self.model.namespace.contribute(result,value,node,force=True)
        return result

    def analyze_attribute(self,plan,node,receiver,environment):
        from .native_classes import Cell,shape,InstanceType
        receiver_kind=shape(receiver)
        if isinstance(receiver_kind,InstanceType):
            owner=self.model.classes[receiver_kind.name]
            member=self.members.get((owner.index,self.model.resolved_name(plan,node)))
            if member is None or member.plan is not None and member.descriptor=="function":return None
            self.check_metadata(member,node)
            if member.plan is not None:
                self.observe_method(member,node)
                from .native_class_descriptors import analyze_member
                value=analyze_member(self,plan,node,member,receiver,environment)
                if value is None:return None
            else:value=self.field(member,node)
            field=owner.fields.get(member.name)
            written=field is not None and field.written
            if written:
                result=Cell()
                self.model.namespace.contribute(result,value,node,force=True)
                self.model.namespace.contribute(result,field.cell,node,force=True)
                value=result
            self.attribute_reads[(plan.index,id(node))]=(member,)
            self.instance_reads[(plan.index,id(node))]=written
            return self.model.remember(plan,node,value)
        choices=self.class_choices(receiver_kind)
        if not choices:return None
        result=Cell()
        records=[]
        for choice in choices:
            member=self.member(self.owners[choice.definition],self.model.resolved_name(plan,node))
            self.check_metadata(member,node)
            if member.plan is not None:
                self.observe_method(member,node)
                from .native_class_descriptors import analyze_member
                value=analyze_member(self,plan,node,member,receiver,environment)
                if value is None:value=member.function_cell
            else:value=self.field(member,node)
            self.model.namespace.contribute(result,value,node,force=True)
            records.append(member)
        self.attribute_reads[(plan.index,id(node))]=tuple(records)
        return self.model.remember(plan,node,result)

    def assign_attribute(self,plan,node,receiver,value,environment):
        from .native_classes import shape,ClassUnsupported
        choices=self.class_choices(shape(receiver))
        if not choices:return False
        for choice in choices:
            member=self.member(self.owners[choice.definition],self.model.resolved_name(plan,node))
            self.check_metadata(member,node)
            if member.plan is not None:
                raise ClassUnsupported(node,"rebinding a class method requires runtime descriptor and instance-attribute lookup updates; that mutation protocol is not implemented",proof="mutable class method descriptor lookup")
            self.contribute(member,value,node,"attribute_store")
        self.model.remember(plan,node,value)
        return True

    @staticmethod
    def check_metadata(member,node):
        from .native_classes import ClassUnsupported
        from .native_module_linking import ANNOTATION_METADATA
        if ClassNamespaces.special_name(member.name):
            raise ClassUnsupported(node,f"class attribute {member.name!r} requires its Python class/annotation metadata descriptor; that metadata protocol is not implemented",proof="class metadata descriptor semantics")

    def analyze_delete(self,plan,node,environment):
        from .native_classes import ClassUnsupported,shape
        if isinstance(node,ast.Name):
            member=self.local_member(plan,node)
            if member is None:return False
            self.field(member,node)
            environment.pop(member.name,None)
            environment.definite.discard(member.name)
            return True
        if not isinstance(node,ast.Attribute):return False
        receiver=self.model.expression(plan,node.value,environment)
        choices=self.class_choices(shape(receiver))
        if not choices:return False
        for choice in choices:
            member=self.member(self.owners[choice.definition],self.model.resolved_name(plan,node))
            self.check_metadata(member,node)
            if member.plan is not None:
                raise ClassUnsupported(node,"deleting a class method requires updating runtime descriptor and instance lookup; that mutation protocol is not implemented",proof="mutable class method descriptor lookup")
            self.field(member,node)
        return True

    def emit_delete(self,emitter,node):
        from .native import _string
        from .native_unions import project,union_kind
        if isinstance(node,ast.Name):
            member=self.local_member(emitter.plan,node)
            if member is None:return None
            setup=""
            def branch(kind,code):return member,"class_scope.globals",f"NameError: name '{member.name}' is not defined"
            choices=((None,None),)
        elif isinstance(node,ast.Attribute)and self.class_choices(emitter.kind(node.value)):
            setup,receiver=emitter.capture(emitter.expression(node.value))
            def branch(kind,code):
                member=self.member(self.owners[kind.definition],self.model.resolved_name(emitter.plan,node))
                return member,f"({code}).module",f"AttributeError: type object '{member.owner.node.name}' has no attribute '{member.name}'"
        else:return None
        def remove(kind,code):
            member,module,message=branch(kind,code)
            index=self.model.namespace.index(member.key)
            removed=emitter.fresh()
            code=(f'{{let {removed}={{{module}.borrow_mut().value_{index}.take()}};'
                  +f'if {removed}.is_some(){{drop({removed});Ok(())}}else{{Err({_string(message)}.to_owned())}}}}')
            return emitter.at(code,node)
        if isinstance(node,ast.Name):code=remove(None,None)
        else:code=project(receiver.kind,receiver.code,remove)if union_kind(receiver.kind)else remove(receiver.kind,receiver.code)
        return setup+code+';'

    def emit_store(self,emitter,member,value,node,module="class_scope.globals"):
        from .native_classes import shape
        index=self.model.namespace.index(member.key)
        stored=dict(self.model.namespace.fields())[member.key]
        return f"{module}.borrow_mut().value_{index}=Some({emitter.coerce(value,stored,node)});"

    def emit_assign_name(self,emitter,node,value):
        member=self.local_member(emitter.plan,node)
        return None if member is None else self.emit_store(emitter,member,value,node)

    def emit_name(self,emitter,node,wanted=None):
        from .native_classes import Expression,shape
        from .native_class_globals import narrow_binding
        from .native import _string
        record=self.name_reads.get((emitter.plan.index,id(node)))
        if record is None:return None
        member,fallback=record
        wanted=wanted or emitter.kind(node)
        index=self.model.namespace.index(member.key)
        stored=dict(self.model.namespace.fields())[member.key]
        if fallback is None:
            failure=emitter.at(f'Err::<{emitter.rust_type(wanted)},String>({_string("NameError: name '"+member.name+"' is not defined")}.into())',node)
        else:
            fallback_stored=dict(self.model.namespace.fields())[fallback]
            global_index=self.model.namespace.index(fallback)
            loaded=emitter.at(f"class_global_get_{global_index}(&class_scope)",node)
            failure=narrow_binding(emitter,node,fallback_stored,wanted,loaded).code
        value=emitter.fresh()
        # The temporary borrow ends before a fallback can run another lookup.
        code=(f"{{let {value}={{class_scope.globals.borrow().value_{index}.clone()}};"
              +f"match {value}{{Some(value)=>{narrow_binding(emitter,node,stored,wanted,'value').code},None=>{failure}}}}}")
        return Expression(code,wanted)

    def emit_get(self,emitter,node,reference,member):
        from .native_classes import Expression
        from .native import _string
        index=self.model.namespace.index(member.key)
        stored=dict(self.model.namespace.fields())[member.key]
        message=f"AttributeError: type object '{member.owner.node.name}' has no attribute '{member.name}'"
        loaded=emitter.at(f'{{let value={reference.code}.module.borrow().value_{index}.clone();value.ok_or_else(||{_string(message)}.to_owned())}}',node)
        return Expression(loaded,stored)

    def emit_attribute(self,emitter,node,receiver):
        from .native_classes import Expression
        from .native_unions import project,union_kind
        records=self.attribute_reads.get((emitter.plan.index,id(node)))
        if records is None:return None
        wanted=emitter.kind(node)
        instance=(emitter.plan.index,id(node))in self.instance_reads
        if instance:
            member=records[0]
            reference=emitter.fresh()
            setup=f"let {reference}={{{receiver.code}.borrow().class_definition.clone()}};"
            class_reference=Expression(reference,ClassReferenceType(member.owner.index))
            loaded=self.emit_get(emitter,node,class_reference,member)
            if member.plan is not None:
                from .native_class_descriptors import emit_member
                before,function=emitter.capture(loaded)
                setup+=before
                result=emit_member(self,emitter,node,member,class_reference,function)
                if result is not None:loaded=result
            fallback=emitter.coerce(loaded,wanted,node)
            if self.instance_reads[(emitter.plan.index,id(node))]:
                from .native_classes import shape
                field=member.owner.fields[member.name]
                index=list(member.owner.fields).index(member.name)
                current=emitter.fresh()
                setup+=f"let {current}={{{receiver.code}.borrow().field_{index}.clone()}};"
                fallback=(f"match {current}{{Some(value)=>{emitter.coerce(Expression('value',shape(field.cell)),wanted,node)},None=>{fallback}}}")
            return Expression("{"+setup+fallback+"}",wanted)
        def branch(kind,code):
            member=next(member for member in records if member.owner.index==kind.definition)
            reference=Expression(f"({code}).clone()",kind)
            loaded=self.emit_get(emitter,node,reference,member)
            if member.plan is not None:
                from .native_class_descriptors import emit_member
                before,function=emitter.capture(loaded)
                result=emit_member(self,emitter,node,member,reference,function)
                if result is not None:loaded=Expression("{"+before+result.code+"}",result.kind)
            return emitter.coerce(loaded,wanted,node)
        code=project(receiver.kind,receiver.code,branch)if union_kind(receiver.kind)else branch(receiver.kind,receiver.code)
        return Expression(code,wanted)

    def emit_definition(self,emitter,node):
        if emitter.plan.class_body is None or not isinstance(node,ast.FunctionDef):return ""
        from .native_classes import Expression,shape
        member=self.member(emitter.plan.class_body,self.model.resolved_name(emitter.plan,node))
        if not member.observed:return ""
        value=Expression(self.model.callable_cells.reference_code(emitter,member.plan),shape(member.function_cell))
        return self.emit_store(emitter,member,value,node)

    def qualname(self,owner):
        parent=self.parents.get(owner.index)
        return (self.qualname(parent)+"."if parent is not None else"")+owner.node.name


def requires_namespaces(program):
    from .native_annotations import executable_nodes
    from .native_module_linking import native_adapter_module_names
    native_adapters=native_adapter_module_names(program)
    for unit in program.units:
        if unit.name in native_adapters:continue
        classes=[node for node in executable_nodes(unit.tree)if isinstance(node,ast.ClassDef)]
        names={node.name for node in classes}
        parents={id(child):parent for parent in executable_nodes(unit.tree)for child in ast.iter_child_nodes(parent)}
        for owner in classes:
            if owner.bases or owner.keywords or owner.decorator_list:return True
            if any(isinstance(node,(ast.ClassDef,ast.Assign,ast.AugAssign,ast.Delete))or isinstance(node,ast.AnnAssign)and node.value is not None or isinstance(node,ast.FunctionDef)and node.decorator_list for node in owner.body):return True
        for node in executable_nodes(unit.tree):
            if not isinstance(node,ast.Name)or not isinstance(node.ctx,ast.Load)or node.id not in names:continue
            parent=parents.get(id(node))
            if not(isinstance(parent,ast.Call)and parent.func is node):return True
    return False
