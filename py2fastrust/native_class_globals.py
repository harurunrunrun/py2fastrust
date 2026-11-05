"""Lexical module bindings in a shared, statically typed native frame.

Binding summaries are distinct from allocation/type union-find cells. Rebinding
a global replaces its optional value; mutable payloads keep their Rc identity.
An empty namespace leaves ClassScope and its clone cost entirely unchanged.
"""
import ast
import builtins

from .native_constraints import Variable,Value,value as constraint_value
from .native_types import (ListType,TupleType,TupleSequenceType,UnionType,NullableType,alternatives,union_type,
                           immutable)


def complete(kind):
    if kind is None:return False
    if isinstance(kind,(ListType,TupleSequenceType)):return complete(kind.element)
    if isinstance(kind,TupleType):return all(complete(field)for field in kind.fields)
    if isinstance(kind,NullableType):return complete(kind.value)
    if isinstance(kind,UnionType):return all(complete(choice)for choice in kind.alternatives)
    return True


class Namespace:
    def __init__(self,model):
        self.model=model
        self.owners={binding.node:binding for binding in model.unit.bindings}if model.unit is not None else{}
        self.cells={}
        self.incoming={}
        self.active=set()
        self.defaults={}
        self.flow_cells=set()
        self.local_values={}
        self.local_schemas={}
        self.join_cells={}
        self.flow_inputs={}
        self.named_values={}
        self.module_points={}
        self.globals_observed=False
        self.builtin_names=frozenset(vars(builtins))|{"__debug__"}
        self.implicit_names=frozenset({"__file__","__package__","__loader__","__spec__","__doc__","__cached__","__annotations__"})

    def is_flow(self,cell):
        root=cell.root()
        return any(root is item for item in self.cells.values())or root in self.flow_cells

    def value_kind(self,variable,sources):
        from .native_classes import shape
        facts=Value()
        for source in sources:
            kind=shape(source)
            if complete(kind):facts=facts.join(constraint_value(kind))
        # These are derived binding-version facts. Recompute from live source
        # cells when their mutable allocation layouts refine; retaining an old
        # List[int] snapshot beside its refined layout would invent a payload.
        self.model.value_constraints.variables[variable]=facts
        return union_type(*facts.alternatives)if facts.alternatives else None

    def contribute(self,destination,source,node,*,force=False):
        """Directional ABI flow from a binding; never widen its source value."""
        from .native_classes import Cell,shape
        from .native_class_storage import check_merge,contains_cell
        left,right=destination.root(),source.root()
        if not(force or self.is_flow(right)or left in self.flow_cells):return False
        if not complete(shape(right)):return False
        if left is right:return True
        if destination.parent is not None:
            destination.parent=None
            destination.tag,destination.args=left.tag,left.args
            destination.list_origins=left.list_origins
            left=destination
        # This creates a new directional ABI view, rather than unifying the
        # source with its destination. A destination containing the scalar
        # source is finite; the reverse would create a real self-reference.
        if contains_cell(right,left):check_merge(left,right,node)
        variable=Variable(("native_global_flow",id(left)),"value")
        if left not in self.flow_inputs:
            self.flow_inputs[left]=set()if left.tag is None else{Cell(left.tag,left.args,list_origins=left.list_origins)}
        inputs=self.flow_inputs[left]
        inputs.add(source)
        kind=self.value_kind(variable,[value for value in inputs if value.root()is not left])
        if kind is None:return False
        replacement=self.representation(kind,list(inputs),node)
        left.tag,left.args=replacement.tag,replacement.args
        left.list_origins=replacement.list_origins
        self.flow_cells.add(left)
        return True

    def local_value(self,plan,node,value):
        from .native_classes import Cell,shape
        from .native_types import reference_cloneable
        name=self.model.resolved_name(plan,node)
        key=plan.index,name
        kind=shape(value)
        if not complete(kind):return value
        from .native_class_storage import shared_element
        if not self.is_flow(value)and key not in self.local_schemas and not(reference_cloneable(kind)or isinstance(kind,TupleSequenceType)and shared_element(kind)):return value
        point=plan.index,id(node)
        result=self.local_values.setdefault(point,Cell())
        self.contribute(result,value,node,force=True)
        schema=self.local_schemas.setdefault(key,Cell())
        self.contribute(schema,value,node,force=True)
        return result

    def prepare_local(self,plan,node,environment):
        from .native_classes import Cell
        name=self.model.resolved_name(plan,node)
        previous=environment.get(name)
        if previous is not None and self.is_flow(previous):
            schema=self.local_schemas.setdefault((plan.index,name),Cell())
            self.contribute(schema,previous,node,force=True)

    def named_value(self,plan,node,value):
        from .native_classes import Cell
        stored=self.model.records.get((plan.index,id(node.target)))
        if stored is None or not self.is_flow(stored):return value
        result=self.named_values.setdefault((plan.index,id(node)),Cell())
        self.contribute(result,value,node,force=True)
        return result

    def comprehension_effects(self,plan,node,before,inside):
        from .native_classes import Environment
        names=set()
        for child in ast.walk(node):
            if not isinstance(child,ast.NamedExpr):continue
            target=child.target
            if self.model.unit is not None:
                binding=self.owners.get(self.model.unit.ordinal(target))
                if binding is None or self.model.unit.scopes[binding.owner].kind=="comprehension":continue
            names.add(self.model.resolved_name(plan,target))
        if not names:return
        possible=Environment(before)
        for name in names:
            if name in inside:possible[name]=inside[name]
        joined=self.model.join(before,possible,node)
        self.model.replace_environment(before,joined)

    def join_values(self,left,right,node,name,role="join"):
        from .native_classes import Cell
        if left.root()is right.root():return left
        if not(self.is_flow(left)or self.is_flow(right)):return None
        result=self.join_cells.setdefault((id(node),name,role),Cell())
        self.contribute(result,left,node,force=True)
        self.contribute(result,right,node,force=True)
        return result

    def local_kind(self,plan,name):
        from .native_classes import shape
        cell=self.local_schemas.get((plan.index,name))
        return None if cell is None else shape(cell)

    def eligible(self,name):
        from .references import CORE_BUILTINS
        model=self.model
        provider=getattr(model,"callable_cells",None)
        function_binding=provider is not None and name in provider.function_bindings
        return ((name not in model.functions or function_binding)and name not in model.classes
                and name not in model.global_symbols and name not in {"__name__","__builtins__"}|self.implicit_names
                and (model.display_name(name)not in self.builtin_names or name in model.global_written_names))

    def owns(self,plan,node):
        name=self.model.resolved_name(plan,node)
        if not self.eligible(name):return False
        if self.model.unit is not None:
            binding=self.owners.get(self.model.unit.ordinal(node))
            return binding is not None and self.model.module_owner(binding.owner)
        return self.model.is_module_plan(plan) or name not in plan.declared

    def detached(self,cell):
        """Never merge an allocation or argument into a module-binding cell."""
        from .native_classes import Cell
        root=cell.root()
        if any(root is item for item in self.cells.values()):
            return Cell(root.tag,root.args,list_origins=root.list_origins)
        return cell

    @staticmethod
    def flattened(cells):
        result=[]
        for cell in cells:
            root=cell.root()
            if root.tag=="union":result.extend(Namespace.flattened(root.args))
            elif root.tag is not None:result.append(root)
        return result

    def representation(self,kind,sources,node):
        from .native_classes import Cell,InstanceType,shape
        sources=self.flattened(sources)
        if getattr(kind,"_native_function_reference",False):return Cell("function",kind.targets)
        if getattr(kind,"_native_namespace_view",False):return Cell("globals_dict")
        if isinstance(kind,NullableType):
            return Cell("union",(Cell("none"),self.representation(kind.value,sources,node)))
        if isinstance(kind,UnionType):
            return Cell("union",tuple(self.representation(choice,sources,node)for choice in kind.alternatives))
        if isinstance(kind,ListType):
            lists=[value for value in sources if value.tag=="list"and shape(value)==kind]
            if not lists:return Cell("list",(self.representation(kind.element,[],node),))
            origins=None if any(value.list_origins is None for value in lists)else frozenset().union(*(value.list_origins for value in lists))
            return Cell("list",lists[0].args,list_origins=origins)
        if isinstance(kind,TupleSequenceType):
            sequences=[value for value in sources if value.tag=="tuple_sequence"and shape(value)==kind]
            return Cell("tuple_sequence",sequences[0].args if sequences else(self.representation(kind.element,[],node),))
        if isinstance(kind,TupleType):
            tuples=[value for value in sources if(value.tag=="tuple"or getattr(value.tag,'_native_tuple_record',False))and shape(value)==kind]
            tag=kind.record.tag if getattr(kind,'_native_named_tuple',False)else'tuple'
            return Cell(tag,tuple(self.representation(field,[value.args[index]for value in tuples],node)
                                      for index,field in enumerate(kind.fields)))
        if isinstance(kind,InstanceType):return Cell("object",(kind.name,))
        return Cell(kind)

    def refresh(self,name,node):
        from .native_classes import Cell,shape
        cell=self.cells.setdefault(name,Cell())
        sources=[value for value in self.incoming.get(name,{}).values()if value.root()is not cell]
        known=[]
        for source in sources:
            kind=shape(source)
            # Container element facts may still be bottom on the first pass.
            if complete(kind):known.append(source)
        if not known:
            # A shared allocation can be mutated by a reached callee before
            # its first element kind is known. Keep that allocation's real
            # element cell; defaulting the namespace first would insert a
            # phantom scalar kind and block the callee's append constraints.
            pending=self.flattened(sources)
            if pending and all(value.tag=='list'for value in pending):
                members={value.args[0].root()for value in pending}
                if len(members)==1:
                    cell.tag,cell.args='list',pending[0].args
                    cell.list_origins=(None if any(value.list_origins is None for value in pending)
                                       else frozenset().union(*(value.list_origins for value in pending)))
            return cell
        variable=Variable(("native_module",name),"value")
        kind=self.value_kind(variable,known)
        if kind is None:return cell
        replacement=self.representation(kind,known,node)
        cell.tag,cell.args=replacement.tag,replacement.args
        cell.list_origins=replacement.list_origins
        return cell

    def read(self,plan,node,environment=None):
        if not self.owns(plan,node):return None
        name=self.model.resolved_name(plan,node)
        if self.model.is_module_plan(plan) and name not in self.active and (environment is None or name in environment):return None
        self.active.add(name)
        schema=self.refresh(name,node)
        if self.model.unit is not None and self.model.is_module_plan(plan) and environment is not None and name in environment:
            return environment[name]
        return schema

    def module_point(self,node,value):
        from .native_classes import Cell
        point=self.module_points.setdefault(id(node),Cell())
        self.contribute(point,value,node,force=True)
        return point

    def import_event(self,plan,node,environment=None):
        """Record canonical binding availability at the real import statement."""
        names=set()
        if self.model.unit is not None:
            for child in ast.walk(node):
                binding=self.owners.get(self.model.unit.ordinal(child))
                if binding is not None and binding.role=="import"and self.model.module_owner(binding.owner):names.add(binding.name)
        elif isinstance(node,ast.Import):names={item.asname or item.name.split('.')[0]for item in node.names}
        if plan.visible_definitions is not None:plan.visible_definitions.update(names)
        if environment is not None:environment.definite.update(names)

    def call_effects(self,caller,callee,environment):
        """Invalidate current module facts for canonical transitive writes."""
        if not self.model.is_module_plan(caller)or self.model.unit is None:return
        unit=self.model.unit
        scopes={unit.scope_for(plan.node).ordinal:plan.index for plan in self.model.plans[1:]}
        writes={}
        for binding in unit.bindings:
            if not self.model.module_owner(binding.owner)or binding.role in {"load","parameter","definition"}:continue
            scope=binding.scope
            while scope is not None and unit.scopes[scope].kind=="comprehension":scope=unit.scopes[scope].parent
            if scope in scopes:writes.setdefault(scopes[scope],set()).add(binding.name)
        pending=[callee.index];seen=set()
        while pending:
            current=pending.pop()
            if current in seen:continue
            seen.add(current);pending.extend(self.model.call_edges.get(current,()))
            for name in writes.get(current,()):
                environment[name]=self.refresh(name,callee.node)
                environment.definite.discard(name)

    def assign(self,plan,node,value,environment):
        if not self.owns(plan,node):return False
        name=self.model.resolved_name(plan,node)
        site=self.model.unit.ordinal(node)if self.model.unit is not None else id(node)
        self.incoming.setdefault(name,{})[site]=value
        if self.model.is_module_plan(plan) and name not in self.active:return False
        self.active.add(name)
        schema=self.refresh(name,node)
        environment[name]=self.module_point(node,value)if self.model.unit is not None and self.model.is_module_plan(plan) else schema
        environment.definite.add(name)
        self.model.remember(plan,node,self.cells[name])
        return True

    def delete(self,plan,node,environment):
        from .native_classes import Cell,ClassUnsupported,shape
        if not isinstance(node,ast.Name):
            raise ClassUnsupported(node,"this delete needs attribute/item binding deletion; only canonical lexical name deletion is implemented here",proof="lexical binding ownership")
        name=self.model.resolved_name(plan,node)
        if not self.owns(plan,node):
            if self.model.is_module_plan(plan) or name not in plan.declared:
                raise ClassUnsupported(node,"this delete needs a nonlocal/free binding cell; lexical closure deletion is not implemented",proof="local/module binding ownership")
            schema=self.local_schemas.setdefault((plan.index,name),Cell())
            values=[environment[name]]if name in environment else plan.locals.get(name,[])
            for value in values:self.contribute(schema,value,node,force=True)
            if self.model.final and shape(schema)is None:schema.tag="none"
            self.model.canonical_local(plan,name,schema)
            self.model.remember(plan,node,schema)
            environment[name]=schema
            environment.definite.discard(name)
            return
        self.active.add(name)
        self.model.remember(plan,node,self.refresh(name,node))
        if self.model.is_module_plan(plan):environment.pop(name,None)
        else:environment[name]=self.cells[name]
        environment.definite.discard(name)

    def default_uninhabited(self):
        for name in self.active:
            cell=self.cells[name].root()
            if cell.tag is None:cell.tag="int"

    def defined_plans(self,caller,node):
        lexical=getattr(self.model,"lexical",None)
        if lexical is not None and isinstance(node,ast.FunctionDef):
            target=lexical.plans.get(self.model.unit.ordinal(node))
            if target is not None and not self.model.module_owner(lexical.parents[lexical.scope(target)]):return(target,)
        if caller.class_body is not None:
            return (caller.class_body.methods[self.model.resolved_name(caller,node)],)
        return (self.model.functions.definitions[node],)

    def define(self,caller,node,environment):
        if isinstance(node,ast.ClassDef):
            body=self.model.classes[self.model.definition_name(node)].body_plan
            if body is not None:self.model.bind_call(caller,node,body,[],[],environment)
            return
        for plan in self.defined_plans(caller,node):
            for name,expression in plan.defaults.items():
                if name in plan.default_literals:continue
                for child in ast.walk(expression):
                    if (caller.class_body is not None and isinstance(child,ast.Name)and isinstance(child.ctx,(ast.Store,ast.Del))
                            and self.model.unit is not None):
                        binding=self.owners.get(self.model.unit.ordinal(child))
                        if binding is not None and self.model.unit.scopes[binding.owner].kind=="class":
                            from .native_classes import ClassUnsupported
                            raise ClassUnsupported(child,"this default expression writes the class namespace; typed class-dictionary initialization and class-attribute lookup are not implemented",proof="class namespace ownership and attribute semantics")
                    if isinstance(child,ast.Name)and self.owns(caller,child):
                        resolved=self.model.resolved_name(caller,child)
                        if resolved not in environment:self.active.add(resolved)
                value=self.model.expression(caller,expression,environment)
                self.model.contribute(plan.default_cells[name],value,expression)
        provider=getattr(self.model,"callable_cells",None)
        key=self.model.definition_name(node)
        if self.model.is_module_plan(caller) and provider is not None and key in provider.function_bindings:
            environment[key]=self.module_point(node,provider.definition_value(node))
            environment.definite.add(key)

    def snapshot(self):
        from .native_classes import shape
        return (tuple((name,shape(self.cells[name]))for name in sorted(self.active)),
                tuple((key,shape(cell))for key,cell in sorted(self.defaults.items())),
                tuple((key,shape(cell))for key,cell in sorted(self.local_schemas.items())),self.globals_observed)

    def fields(self):
        from .native_classes import shape
        return [(name,shape(self.cells[name]))for name in sorted(self.active)]

    def index(self,name):
        return sorted(self.active).index(name)

    def default_fields(self):
        from .native_classes import shape
        return [(key,shape(cell))for key,cell in sorted(self.defaults.items())]


def default_read(emitter,plan,name):
    lexical=emitter.model.lexical.default_read(emitter,plan,name)
    if lexical is not None:return lexical
    from .native_classes import Expression,shape
    index=sorted(emitter.model.namespace.defaults).index((plan.index,name))
    code=f'class_default_get_{index}(&class_scope)'
    return Expression(code,shape(plan.default_cells[name]))


def define(emitter,node):
    code=[]
    namespace=emitter.model.namespace
    if isinstance(node,ast.ClassDef):
        body=emitter.model.classes[emitter.model.definition_name(node)].body_plan
        from .native_globals_view import store
        if body is None:return store(emitter,node)
        from .native_class_calls import call
        return call(emitter,f'class_function_{body.index}(class_scope.clone())',body,node)+";"+store(emitter,node)
    fields=sorted(namespace.defaults)
    for plan in namespace.defined_plans(emitter.plan,node):
        for name,expression in plan.defaults.items():
            if name in plan.default_literals:continue
            before,value=emitter.capture(emitter.expression(expression))
            index=fields.index((plan.index,name))
            from .native_classes import shape
            code.append(before+f'class_scope.globals.borrow_mut().default_{index}=Some({emitter.coerce(value,shape(plan.default_cells[name]),expression)});')
    provider=getattr(emitter.model,"callable_cells",None)
    if provider is not None:code.append(provider.definition_emission(emitter,node))
    from .native_globals_view import store
    code.append(store(emitter,node))
    return "".join(code)


def read(emitter,node,wanted):
    from .native_classes import Expression
    from .native_class_binding_contexts import read as class_binding_read
    class_binding=class_binding_read(emitter,node,wanted)
    if class_binding is not None:return class_binding
    namespace=emitter.model.namespace
    name=emitter.model.resolved_name(emitter.plan,node)
    if name not in namespace.active or not namespace.owns(emitter.plan,node):return None
    from .native_global_callable_payload import read as payload_read
    payload=payload_read(emitter,node,wanted)
    if payload is not None:return payload
    index=namespace.index(name)
    loaded=emitter.at(f"class_global_get_{index}(&class_scope)",node)
    return narrow_binding(emitter,node,dict(namespace.fields())[name],wanted,loaded)


def local_read(emitter,node,wanted):
    from .native import _string
    from .native_classes import Expression
    from .native_unions import project,union_kind
    namespace=emitter.model.namespace
    name=emitter.model.resolved_name(emitter.plan,node)
    stored=namespace.local_kind(emitter.plan,name)
    if stored is None:return None
    slot=emitter.slot(name,stored)
    error="NameError"if emitter.model.is_module_plan(emitter.plan) else"UnboundLocalError"
    message=(f"name '{emitter.model.display_name(name)}' is not defined"if error=="NameError"else
             f"cannot access local variable '{emitter.model.display_name(name)}' where it is not associated with a value")
    loaded=emitter.at(f"{slot}.clone().ok_or_else(||{_string(error+': '+message)}.to_owned())",node)
    return narrow_binding(emitter,node,stored,wanted,loaded)


def narrow_binding(emitter,node,stored,wanted,loaded):
    from .native_classes import Expression
    from .native_unions import project,union_kind
    def narrow(kind,code):
        if kind==wanted:return code
        if getattr(kind,"_native_function_reference",False)and getattr(wanted,"_native_function_reference",False):
            from .native_callable_carriers import convert
            return convert(emitter,node,kind,wanted,code,narrow=True)
        if union_kind(kind):
            return project(kind,code,lambda branch,value:narrow(branch,f"({value}).clone()"))
        if kind in alternatives(wanted)or wanted=="int_bool"and kind in {"int","bool"}:
            return emitter.coerce(Expression(code,kind),wanted,node)
        if kind=="int_bool"and wanted in {"int","bool"}:
            variant="Int"if wanted=="int"else"Bool"
            return f'match {code}{{NativeScalar::{variant}(value)=>value,_=>unreachable!("local binding contradicts solved control flow")}}'
        return 'unreachable!("local binding contradicts solved control flow")'
    return Expression(narrow(stored,loaded),wanted)


def local_assign(emitter,node,value):
    name=emitter.model.resolved_name(emitter.plan,node)
    kind=emitter.model.namespace.local_kind(emitter.plan,name)
    if kind is None:return None
    slot=emitter.slot(name,kind)
    return f"{slot}=Some({emitter.coerce(value,kind,node)});"


def assign(emitter,node,value):
    namespace=emitter.model.namespace
    name=emitter.model.resolved_name(emitter.plan,node)
    if name not in namespace.active or not namespace.owns(emitter.plan,node):return None
    index=namespace.index(name)
    kind=dict(namespace.fields())[name]
    return f"class_scope.globals.borrow_mut().value_{index}=Some({emitter.coerce(value,kind,node)});"


def delete(emitter,node):
    from .native import _string
    namespace=emitter.model.namespace
    name=emitter.model.resolved_name(emitter.plan,node)
    if not namespace.owns(emitter.plan,node):
        stored=namespace.local_kind(emitter.plan,name)
        slot=emitter.slot(name,stored)
        message=_string(f"UnboundLocalError: cannot access local variable '{emitter.model.display_name(name)}' where it is not associated with a value")
        code=f'if {slot}.take().is_none(){{Err({message}.to_owned())}}else{{Ok(())}}'
        return emitter.at(code,node)+";"
    index=namespace.index(name)
    message=_string(f"NameError: name '{emitter.model.display_name(name)}' is not defined")
    code=f'if class_scope.globals.borrow_mut().value_{index}.take().is_none(){{Err({message}.to_owned())}}else{{Ok(())}}'
    from .native_globals_view import store
    return emitter.at(code,node)+";"+store(emitter,node,present=False)


def runtime(source,model,emitter):
    from .native import _string
    fields=model.namespace.fields()
    defaults=model.namespace.default_fields()
    observed=model.namespace.globals_observed
    if not fields and not defaults and not observed:return source
    members=",".join(f"{prefix}_{index}:Option<{emitter.rust_type(kind)}>"for prefix,items in (("value",fields),("default",defaults))for index,(_,kind)in enumerate(items))
    initialized=",".join(f"{prefix}_{index}:None"for prefix,items in (("value",fields),("default",defaults))for index in range(len(items)))
    if observed:
        from .native_globals_view import names
        all_names,initial=names(model.namespace)
        members+=(","if members else"")+f"present:[bool;{len(all_names)}]"
        initialized+=(","if initialized else"")+"present:["+','.join(str(name in initial).lower()for name in all_names)+"]"
    declaration=f"struct ClassGlobals{{{members}}}\n"
    from .native_globals_view import runtime as globals_runtime
    declaration+=globals_runtime(model.namespace)
    for index,(name,kind)in enumerate(fields):
        error=_string(f"NameError: name '{model.display_name(name)}' is not defined")
        if name in model.callable_cells.fallback_names:
            from .native_classes import Expression,shape
            from .native_aot_callables import variant
            custom=getattr(model.namespace,"fallback_runtime",lambda *_:None)(emitter,name,kind)
            if custom is not None:loaded=custom
            else:
                builtin=model.callable_cells.builtin_cells[name]
                from .references import BuiltinIdentity
                fallback=emitter.coerce(Expression(variant(BuiltinIdentity(model.callable_cells.spelling(name))),shape(builtin)),kind,model.module.node)
                loaded=f"Ok(scope.globals.borrow().value_{index}.clone().unwrap_or_else(||{fallback}))"
        else:loaded=f"scope.globals.borrow().value_{index}.clone().ok_or_else(||{error}.to_owned())"
        declaration+=(f"fn class_global_get_{index}(scope:&ClassScope)->Result<{emitter.rust_type(kind)},String>{{{loaded}}}\n")
    from .native_global_callable_payload import runtime as payload_runtime
    declaration+=payload_runtime(model)
    for index,(_,kind)in enumerate(defaults):
        declaration+=(f"fn class_default_get_{index}(scope:&ClassScope)->{emitter.rust_type(kind)}{{"
                      f'scope.globals.borrow().default_{index}.clone().expect("definition-time default must be initialized")}}\n')
    before="struct ClassScope { control: Rc<RefCell<ClassControl>>, io: Rc<RefCell<ClassIo>> }"
    after="struct ClassScope { control: Rc<RefCell<ClassControl>>, io: Rc<RefCell<ClassIo>>, globals: Rc<RefCell<ClassGlobals>> }"
    assert source.count(before)==1
    source=source.replace(before,after)
    before="io:Rc::new(RefCell::new(ClassIo{input:StandardInput::new(),output:String::new()}))"
    assert source.count(before)==1
    source=source.replace(before,before+f",globals:Rc::new(RefCell::new(ClassGlobals{{{initialized}}}))")
    return declaration+source

